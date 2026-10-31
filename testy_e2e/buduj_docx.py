#!/usr/bin/env python3
"""Builds korpus/01-wezwanie.docx from korpus/01-wezwanie.txt (one paragraph per line).

Needs python-docx (in the project's .venv); run:
    .venv/bin/python testy_e2e/buduj_docx.py
It only builds the DOCX file of document 01, with the same content and the same expectations list.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document


def main() -> int:
    katalog = Path(__file__).parent / "korpus"
    plik_txt = katalog / "01-wezwanie.txt"
    plik_docx = katalog / "01-wezwanie.docx"
    dokument = Document()
    for linia in plik_txt.read_text(encoding="utf-8").splitlines():
        dokument.add_paragraph(linia)
    dokument.save(plik_docx)
    print(f"zapisano: {plik_docx}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
