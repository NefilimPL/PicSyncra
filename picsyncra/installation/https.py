"""Verified HTTPS for installed tools, including fresh Windows service profiles."""
import ssl
import certifi


def verified_https_context():
    context = ssl.create_default_context()
    # Keep machine/user trust (including corporate CAs) and supplement it with
    # bundled public roots. Fresh Sandbox/SYSTEM profiles may have no roots yet.
    context.load_verify_locations(cafile=certifi.where())
    return context
