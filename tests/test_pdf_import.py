"""Tests für pdf_import.py – kein Live-Netzwerk, Gemini-Aufrufe gemockt."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from shiori import gemini_client
from shiori import pdf_import


def _make_pdf_with_text(text: str) -> bytes:
    """Minimales PDF mit echtem Textlayer per PyMuPDF selbst erzeugen -
    schont Live-Netzwerk/Fixtures und testet trotzdem den echten Code-Pfad."""
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _make_blank_pdf_page() -> bytes:
    """PDF-Seite ganz ohne Text (simuliert eine gescannte Seite ohne Textlayer)."""
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


# --------------------------------------------------------------------------- #
# _guess_kind / _image_mime_type
# --------------------------------------------------------------------------- #

def test_guess_kind_detects_pdf_by_extension():
    assert pdf_import._guess_kind("buch.pdf", None) == "pdf"


def test_guess_kind_detects_pdf_by_content_type():
    assert pdf_import._guess_kind("upload", "application/pdf") == "pdf"


def test_guess_kind_detects_image_by_extension():
    assert pdf_import._guess_kind("seite.png", None) == "image"
    assert pdf_import._guess_kind("foto.JPG", None) == "image"


def test_guess_kind_detects_image_by_content_type():
    assert pdf_import._guess_kind("upload", "image/png") == "image"


def test_guess_kind_raises_for_unsupported_type():
    with pytest.raises(pdf_import.ExtractionError):
        pdf_import._guess_kind("video.mp4", "video/mp4")


def test_image_mime_type_prefers_content_type():
    assert pdf_import._image_mime_type("x.png", "image/webp") == "image/webp"


def test_image_mime_type_falls_back_to_extension():
    assert pdf_import._image_mime_type("x.jpeg", None) == "image/jpeg"
    assert pdf_import._image_mime_type("x.unknown", None) == "image/png"


# --------------------------------------------------------------------------- #
# extract_pdf_text
# --------------------------------------------------------------------------- #

def test_extract_pdf_text_reads_text_layer_without_gemini_key():
    data = _make_pdf_with_text("Hallo Welt")
    text = pdf_import.extract_pdf_text(data, gemini_key=None)
    assert "Hallo Welt" in text


def test_extract_pdf_text_skips_page_without_textlayer_and_no_key():
    data = _make_blank_pdf_page()
    text = pdf_import.extract_pdf_text(data, gemini_key=None)
    assert text == ""


def test_extract_pdf_text_ocrs_page_without_textlayer_when_key_given(monkeypatch):
    data = _make_blank_pdf_page()
    calls = []

    def fake_transcribe(image_bytes, api_key, *, mime_type="image/png", model=None, session=None, use_cache=True, **kwargs):
        calls.append((api_key, mime_type))
        return "OCR-Ergebnis"

    monkeypatch.setattr(gemini_client, "transcribe_image", fake_transcribe)
    text = pdf_import.extract_pdf_text(data, gemini_key="mykey")
    assert text == "OCR-Ergebnis"
    assert calls == [("mykey", "image/png")]


def test_extract_pdf_text_continues_when_ocr_fails_for_one_page(monkeypatch):
    # Zwei-Seiten-PDF, beide ohne Textlayer; die erste OCR schlägt fehl -
    # die zweite Seite soll trotzdem verarbeitet werden (kein harter Abbruch).
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    data = doc.tobytes()
    doc.close()

    responses = iter([None, "Seite 2 Text"])
    monkeypatch.setattr(
        gemini_client, "transcribe_image",
        lambda *a, **k: next(responses),
    )
    text = pdf_import.extract_pdf_text(data, gemini_key="mykey")
    assert text == "Seite 2 Text"


def test_extract_pdf_text_raises_for_corrupt_pdf():
    with pytest.raises(pdf_import.ExtractionError):
        pdf_import.extract_pdf_text(b"not a pdf", gemini_key=None)


def test_extract_pdf_text_caps_page_count(monkeypatch):
    monkeypatch.setattr(pdf_import, "_MAX_PDF_PAGES", 2)
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    for i in range(4):
        page = doc.new_page()
        page.insert_text((72, 72), f"Seite {i}")
    data = doc.tobytes()
    doc.close()

    text = pdf_import.extract_pdf_text(data, gemini_key=None)
    assert "Seite 0" in text
    assert "Seite 1" in text
    assert "Seite 2" not in text
    assert "Seite 3" not in text


# --------------------------------------------------------------------------- #
# extract_image_text
# --------------------------------------------------------------------------- #

def test_extract_image_text_requires_gemini_key():
    with pytest.raises(pdf_import.ExtractionError):
        pdf_import.extract_image_text(b"imgbytes", gemini_key=None)


def test_extract_image_text_returns_transcription(monkeypatch):
    monkeypatch.setattr(gemini_client, "transcribe_image", lambda *a, **k: "erkannter Text")
    text = pdf_import.extract_image_text(b"imgbytes", gemini_key="mykey")
    assert text == "erkannter Text"


def test_extract_image_text_raises_when_transcription_fails(monkeypatch):
    monkeypatch.setattr(gemini_client, "transcribe_image", lambda *a, **k: None)
    with pytest.raises(pdf_import.ExtractionError):
        pdf_import.extract_image_text(b"imgbytes", gemini_key="mykey")


# --------------------------------------------------------------------------- #
# extract_text_from_upload (Dispatch)
# --------------------------------------------------------------------------- #

def test_extract_text_from_upload_dispatches_to_pdf():
    data = _make_pdf_with_text("PDF-Inhalt")
    text = pdf_import.extract_text_from_upload(data, "datei.pdf", "application/pdf", gemini_key=None)
    assert "PDF-Inhalt" in text


def test_extract_text_from_upload_dispatches_to_image(monkeypatch):
    monkeypatch.setattr(gemini_client, "transcribe_image", lambda *a, **k: "Bild-Text")
    text = pdf_import.extract_text_from_upload(b"imgbytes", "foto.png", "image/png", gemini_key="mykey")
    assert text == "Bild-Text"


def test_extract_text_from_upload_raises_for_unsupported_extension():
    with pytest.raises(pdf_import.ExtractionError):
        pdf_import.extract_text_from_upload(b"data", "archiv.zip", "application/zip", gemini_key=None)
