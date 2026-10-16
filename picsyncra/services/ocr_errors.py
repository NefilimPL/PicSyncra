"""OCR-owned diagnostics, also usable with an older pinned application host.

Keep this independent of installation.ocr_errors: installation helpers are
embedded in hosts and cannot be supplied by an update of the OCR module.
"""


def format_ocr_error(error: BaseException, *, limit: int = 2048) -> str:
    chain = []
    seen = set()
    current = error
    while current is not None and id(current) not in seen and len(chain) < 16:
        seen.add(id(current))
        chain.append(f"{type(current).__name__}: {current}")
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    return " <- ".join(reversed(chain))[:limit]
