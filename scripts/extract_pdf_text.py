"""Bounded PyPDF2 fallback used when the native pdftotext command is unavailable."""

import sys

from PyPDF2 import PdfReader


def main():
    filepath = sys.argv[1]
    max_pages = int(sys.argv[2])
    max_chars = int(sys.argv[3])
    reader = PdfReader(filepath, strict=False)
    parts = []
    size = 0
    for page in reader.pages[:max_pages]:
        try:
            extracted = page.extract_text() or ""
        except Exception:
            continue
        if not extracted:
            continue
        remaining = max_chars - size
        if remaining <= 0:
            break
        parts.append(extracted[:remaining])
        size += len(parts[-1])
    text = "\n".join(parts).strip()
    if not text:
        return 2
    sys.stdout.write(text[:max_chars])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
