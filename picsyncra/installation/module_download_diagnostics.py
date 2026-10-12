"""Bounded, public download diagnostics without URLs or raw exception text."""
import errno
import http.client
import socket
import ssl
from urllib.error import HTTPError, URLError


def download_failure(exc):
    if isinstance(exc, HTTPError):
        return dict(code='http_error', message=f'GitHub zwrócił HTTP {exc.code}.',
                    http_status=exc.code, retryable=exc.code in {408, 429, 500, 502, 503, 504})
    reason = exc.reason if isinstance(exc, URLError) else exc
    if isinstance(reason, ssl.SSLCertVerificationError):
        return dict(code='certificate_error', message='Nie udało się zweryfikować certyfikatu serwera.', retryable=False)
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return dict(code='timeout', message='Przekroczono czas pobierania pliku.', retryable=True)
    if isinstance(reason, socket.gaierror):
        return dict(code='dns_error', message='Nie udało się odczytać adresu serwera (DNS).', retryable=True)
    if isinstance(reason, http.client.IncompleteRead):
        return dict(code='interrupted_download', message='Serwer przerwał przesyłanie pliku.', retryable=True)
    if isinstance(exc, URLError) or isinstance(reason, (ConnectionError, ssl.SSLError)):
        return dict(code='connection_error', message='Połączenie podczas pobierania zostało przerwane.', retryable=True,
                    **({'system_code': reason.errno} if isinstance(getattr(reason, 'errno', None), int) else {}))
    if isinstance(reason, OSError):
        return dict(code='disk_full' if reason.errno == errno.ENOSPC else 'local_io_error',
                    message='Brak miejsca na dysku.' if reason.errno == errno.ENOSPC else 'Nie udało się zapisać lub odczytać pliku lokalnego.',
                    retryable=False, system_code=getattr(reason, 'winerror', None) or reason.errno)
    return dict(code='invalid_source', message='Nieprawidłowe źródło pobierania modułu.', retryable=False)
