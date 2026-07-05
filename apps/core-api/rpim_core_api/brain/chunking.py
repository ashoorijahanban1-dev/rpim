def chunk_text(text: str, max_chars: int = 700, overlap: int = 100) -> list[str]:
    """Persian-aware-enough chunker for M2: packs whole paragraphs up to
    max_chars; oversized paragraphs are windowed with `overlap` shared chars
    so retrieval never loses sentence context at boundaries."""
    text = (text or "").strip()
    if not text:
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buffer = ""

    def flush() -> None:
        nonlocal buffer
        if buffer.strip():
            chunks.append(buffer.strip())
        buffer = ""

    for paragraph in paragraphs:
        if len(paragraph) <= max_chars:
            if not buffer:
                buffer = paragraph
            elif len(buffer) + 2 + len(paragraph) <= max_chars:
                buffer = f"{buffer}\n\n{paragraph}"
            else:
                flush()
                buffer = paragraph
            continue

        flush()
        start = 0
        while start < len(paragraph):
            end = min(start + max_chars, len(paragraph))
            piece = paragraph[start:end].strip()
            if piece:
                chunks.append(piece)
            if end == len(paragraph):
                break
            start = end - overlap

    flush()
    return chunks
