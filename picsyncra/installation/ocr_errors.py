"""Small serializable OCR errors, including the cause hidden by PaddleOCR."""


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
    # Keep the root cause first so long wrapper messages cannot hide it.
    return " <- ".join(reversed(chain))[:limit]
