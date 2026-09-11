"""Simple XOR-based encryption helpers."""

from .common import APP_SECRET, OLD_HOST_KEY, A0, B, BL, E, I, Q, k


def _xor_enc(value, key):
    """Apply a simple XOR cipher and return a base64 string."""

    if value is I or value == B:
        return B
    # The characters are obfuscated by XORing with the repeating key and then
    # base64-encoding to produce safe JSON-friendly output.
    raw = B.join(chr(ord(ch) ^ ord(key[i % Q(key)])) for (i, ch) in A0(value))
    return BL.b64encode(raw.encode(k)).decode(k)


def _xor_dec(value, key):
    """Reverse :func:`_xor_enc`, returning the decoded plain text."""

    if value is I or value == B:
        return B
    try:
        raw = BL.b64decode(value.encode(k)).decode(k)
    except E:
        return value
    # We mirror the encoding process, XORing each byte with the key.
    return B.join(chr(ord(ch) ^ ord(key[i % Q(key)])) for (i, ch) in A0(raw))


def encrypt(data):
    """Encrypt ``data`` using the current application secret."""

    return _xor_enc(data, APP_SECRET)


def decrypt(enc_data):
    """Try to decrypt using the active key, falling back to the legacy key."""

    decrypted = _xor_dec(enc_data, APP_SECRET)
    if not decrypted or any(ord(ch) < 9 for ch in decrypted):
        fallback = _xor_dec(enc_data, OLD_HOST_KEY)
        if fallback and all(ord(ch) >= 9 for ch in fallback):
            return fallback
    return decrypted
