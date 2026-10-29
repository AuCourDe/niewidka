#!/usr/bin/env python3
"""Buduje korpus/01-wezwanie.docx z korpus/01-wezwanie.txt (jeden akapit na linię).

Wymaga python-docx (jest w .venv projektu); uruchamiać:
    .venv/bin/python testy_e2e/buduj_docx.py
Tylko buduje plik DOCX z dokumentu 01, treść i taką samą listę oczekiwań.
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
