"""Native Windows credentials, held only for one controller-owned operation.

Passwords stay in clearable native buffers. Only a machine-DPAPI protected,
request-bound blob crosses the existing authenticated, local administrator pipe.
Neither blobs nor tokens belong in plans, journals, URLs or command lines.
"""
from contextlib import contextmanager
import base64
import ctypes
from ctypes import wintypes
import sys


class AuthorizationError(RuntimeError):
    def __init__(self, message, *, code='authorization_failed', system_code=None):
        super().__init__(message)
        self.details = dict(code=code, message=message, system_code=system_code, retryable=True)


class _Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.c_void_p)]


class _CredUI(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('parent', wintypes.HWND),
               ('message', wintypes.LPCWSTR), ('caption', wintypes.LPCWSTR), ('banner', wintypes.HANDLE)]


def _windows():
    if sys.platform != 'win32':
        raise AuthorizationError('Jednorazowe logowanie wymaga Windows na komputerze hostującym PicSyncra.')


def _zero(pointer, size):
    if pointer and size: ctypes.memset(pointer, 0, size)


@contextmanager
def _dpapi(data, entropy, *, encrypt):
    _windows()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    entropy_buffer = ctypes.create_string_buffer(entropy)
    entropy_blob = _Blob(len(entropy), ctypes.cast(entropy_buffer, ctypes.c_void_p))
    output = _Blob()
    function = crypt.CryptProtectData if encrypt else crypt.CryptUnprotectData
    function.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob), ctypes.c_void_p,
                         ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(data), None, ctypes.byref(entropy_blob), None, None,
                    5 if encrypt else 1, ctypes.byref(output)):
        raise AuthorizationError('Windows nie może zabezpieczyć jednorazowego logowania.', system_code=ctypes.get_last_error())
    try: yield output
    finally:
        _zero(output.data, output.size)
        kernel.LocalFree(output.data)


def _binding(installation_id, request_id):
    return ('PicSyncra.module-update/' + installation_id + '/' + request_id).encode('ascii')


def prompt_credentials(installation_id, request_id, *, parent=None):
    """Return an encrypted blob, or None when the native dialog is cancelled."""
    _windows()
    api = ctypes.WinDLL('credui', use_last_error=True)
    ole = ctypes.WinDLL('ole32', use_last_error=True)
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    api.CredUIPromptForWindowsCredentialsW.argtypes = [ctypes.POINTER(_CredUI), wintypes.DWORD,
        ctypes.POINTER(wintypes.ULONG), ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.ULONG), ctypes.c_void_p, wintypes.DWORD]
    api.CredUIPromptForWindowsCredentialsW.restype = wintypes.DWORD
    info = _CredUI(ctypes.sizeof(_CredUI), parent,
                   'Podaj konto lokalne lub domenowe z dostępem do plików PicSyncra. Logowanie dotyczy tylko tej instalacji aktualizacji.',
                   'PicSyncra — jednorazowa instalacja aktualizacji', None)
    package = wintypes.ULONG()
    pointer = ctypes.c_void_p()
    size = wintypes.ULONG()
    # GENERIC: username/password; no save checkbox or stored credential lookup.
    result = api.CredUIPromptForWindowsCredentialsW(ctypes.byref(info), 0, ctypes.byref(package), None, 0,
                ctypes.byref(pointer), ctypes.byref(size), None, 1)
    if result == 1223: return None
    if result:
        raise AuthorizationError('Windows nie może otworzyć okna logowania.', system_code=result)
    try:
        if not 0 < size.value <= 4096:
            raise AuthorizationError('Windows zwrócił nieobsługiwany format danych logowania.')
        with _dpapi(_Blob(size.value, pointer), _binding(installation_id, request_id), encrypt=True) as protected:
            return base64.b64encode(ctypes.string_at(protected.data, protected.size)).decode('ascii')
    finally:
        _zero(pointer, size.value)
        ole.CoTaskMemFree(pointer)


class WindowsAuthorization:
    def __init__(self, handle): self.handle = handle

    @contextmanager
    def scope(self):
        if not self.handle:
            raise AuthorizationError('Jednorazowe logowanie wygasło. Przygotuj nowy plan.')
        api = ctypes.WinDLL('advapi32', use_last_error=True)
        api.ImpersonateLoggedOnUser.argtypes = [wintypes.HANDLE]
        api.ImpersonateLoggedOnUser.restype = wintypes.BOOL
        api.RevertToSelf.restype = wintypes.BOOL
        if not api.ImpersonateLoggedOnUser(self.handle):
            raise AuthorizationError('Windows nie może użyć tego konta do instalacji.', system_code=ctypes.get_last_error())
        try: yield
        finally:
            if not api.RevertToSelf():
                # Continuing a controller thread under another identity is
                # unsafe. Fail closed; Windows releases the token at process exit.
                import os
                os._exit(1)

    def close(self):
        if self.handle:
            api = ctypes.WinDLL('kernel32', use_last_error=True)
            api.CloseHandle.argtypes = [wintypes.HANDLE]
            api.CloseHandle(self.handle)
            self.handle = None


def logon_credentials(installation_id, request_id, credential_blob):
    """Verify local/domain credentials and return a temporary impersonation token."""
    _windows()
    packed = bytearray(base64.b64decode(credential_blob, validate=True))
    buffer = (ctypes.c_char * len(packed)).from_buffer(packed)
    try:
        with _dpapi(_Blob(len(packed), ctypes.cast(buffer, ctypes.c_void_p)),
                    _binding(installation_id, request_id), encrypt=False) as data:
            cred = ctypes.WinDLL('credui', use_last_error=True)
            cred.CredUnPackAuthenticationBufferW.argtypes = [wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
            cred.CredUnPackAuthenticationBufferW.restype = wintypes.BOOL
            lengths = [wintypes.DWORD(513), wintypes.DWORD(257), wintypes.DWORD(257)]
            username, domain, password = [ctypes.create_unicode_buffer(length.value) for length in lengths]
            try:
                if not cred.CredUnPackAuthenticationBufferW(0, data.data, data.size, username, ctypes.byref(lengths[0]),
                            domain, ctypes.byref(lengths[1]), password, ctypes.byref(lengths[2])):
                    raise AuthorizationError('Nieobsługiwany format logowania Windows.', system_code=ctypes.get_last_error())
                # CredUI may provide DOMAIN\user or a UPN in the username field.
                # Split only the username; do not materialize the password as a Python string.
                name, realm = username.value, domain.value
                if '\\' in name: realm, name = name.split('\\', 1)
                username.value = name
                domain.value = realm
                api = ctypes.WinDLL('advapi32', use_last_error=True)
                api.LogonUserW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                          wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
                api.LogonUserW.restype = wintypes.BOOL
                handle = wintypes.HANDLE()
                # NETWORK_CLEARTEXT keeps network credentials for this logon
                # session; closing the final token ends it. No app credential store.
                if not api.LogonUserW(username, domain if realm else None, password, 8, 0, ctypes.byref(handle)):
                    raise AuthorizationError('Windows odrzucił logowanie. Sprawdź konto, domenę i hasło.',
                                             code='logon_failed', system_code=ctypes.get_last_error())
                return WindowsAuthorization(handle)
            finally:
                for value in (username, domain, password): _zero(value, ctypes.sizeof(value))
    finally: _zero(buffer, len(packed))
