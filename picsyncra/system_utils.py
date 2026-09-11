"""System-related helpers."""

from .common import *  # noqa: F401,F403


def is_admin():
    """Best-effort check for administrator rights on the current system."""

    try:
        if A.name == "nt":
            result = ctypes.windll.shell32.ShellExecuteW(AQ, "runas", "cmd.exe", "/c exit", AQ, 1)
            return result > 32
        return Al
    except E:
        return Ay


def get_file_lock_user(path):
    """Attempt to discover which user has locked ``path`` in Excel."""

    encoding_fallback = "latin-1"
    errors_mode = "ignore"
    target = path
    if not A.path.exists(target):
        return h
    try:
        handle = A.open(target, A.O_RDWR | A.O_EXCL)
        A.close(handle)
        return h
    except Au:
        directory = A.path.dirname(target)
        filename = A.path.basename(target)
        lock_path = A.path.join(directory, "~$" + filename)
        if A.path.exists(lock_path):
            try:
                with x(lock_path, "rb") as handle:
                    data = handle.read()
                    if Q(data) >= 2:
                        # XLSX lock files store the username length in the
                        # second byte followed by the UTF-16 encoded payload.
                        name_length = data[1]
                        if 2 + name_length <= Q(data):
                            raw_name = data[2 : 2 + name_length]
                            try:
                                decoded = raw_name.decode(k, errors=errors_mode).strip()
                            except Exception:
                                decoded = raw_name.decode(encoding_fallback, errors=errors_mode).strip()
                            if decoded:
                                return decoded
                    text = data.decode(k, errors=errors_mode)
                    if not text or text.count("\x00") > 0:
                        text = data.decode(encoding_fallback, errors=errors_mode)
                    cleaned = text.replace(filename, B)
                    candidates = [item for item in cleaned.split() if 3 <= Q(item) <= 50]
                    if candidates:
                        return max(candidates, key=Q)
            except E:
                pass
        return J
