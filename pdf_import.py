#!/usr/bin/env python3
"""pdf_import.py – Text aus hochgeladenen PDFs und Bildern für den Text-Modus
extrahieren, bevor er durch die bestehende Text-/KI-Analyse läuft.

Zweistufig statt "alles auf einmal mit Gemini": PDF-Seiten mit Textlayer
werden direkt und kostenlos ausgelesen (PyMuPDF, reines Python-Wheel ohne
System-Abhängigkeit wie z. B. poppler-utils). Nur Seiten OHNE Textlayer
(Scans) sowie direkt hochgeladene Bilder werden als Bild an Gemini
geschickt und dort transkribiert (`gemini_client.transcribe_image()`) –
bessere OCR-Qualität für Japanisch (Furigana, vertikaler Text, Manga-Fonts)
als lokale OCR-Engines wie Tesseract, ohne eine weitere System-Abhängigkeit.

Der extrahierte Text landet unverändert in derselben Textarea wie
manuell eingefügter Text – die eigentliche Analyse (Janome/WaniKani bzw.
Gemini-Satzanalyse) bleibt exakt dieselbe, nur die Texteingabe kommt aus
einer Datei statt per Copy-Paste.
"""
from __future__ import annotations

import logging
from typing import Any

import gemini_client

logger = logging.getLogger(__name__)

# Ein einzelnes, sehr langes Dokument würde sonst potenziell dutzende
# Gemini-Vision-Requests auslösen (eine pro Scan-Seite) - Deckel, damit ein
# versehentlich hochgeladenes 500-Seiten-Buch nicht den Server minutenlang
# blockiert. Wer mehr braucht, teilt das PDF vorher auf.
_MAX_PDF_PAGES = 30

# Rendering-Auflösung für Seiten ohne Textlayer, die an Gemini gehen -
# genug für gute OCR-Qualität auch bei kleiner Furigana, ohne unnötig große
# Bilder (und damit Base64-Payload) zu erzeugen.
_OCR_RENDER_DPI = 200

# Eine Seite gilt als "ohne Textlayer" (Scan), wenn nach dem Entfernen von
# Whitespace praktisch nichts übrig bleibt - ein einzelnes Satzzeichen o. Ä.
# aus fehlerhafter Text-Extraktion zählt nicht als "hat Text".
_MIN_TEXT_CHARS = 3

_IMAGE_MIME_BY_EXT = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}


class ExtractionError(Exception):
    """Verständlicher Fehler ohne Stacktrace, wenn eine Datei nicht
    verarbeitet werden kann (falscher Typ, kaputte Datei, o. Ä.)."""


def _require_fitz() -> Any:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover - umgebungsabhängig
        raise ExtractionError(
            "Für PDF-Import wird das Paket 'pymupdf' benötigt. Bitte installieren: pip install pymupdf"
        ) from exc
    return fitz


def _guess_kind(filename: str, content_type: str | None) -> str:
    """'pdf' oder 'image' anhand Dateiendung/Content-Type bestimmen."""
    name = (filename or "").lower()
    if name.endswith(".pdf") or (content_type or "") == "application/pdf":
        return "pdf"
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    if ext in _IMAGE_MIME_BY_EXT or (content_type or "").startswith("image/"):
        return "image"
    raise ExtractionError(
        f"Nicht unterstützter Dateityp „{filename}“ – erlaubt sind PDF und Bilder (PNG/JPEG/WebP/GIF)."
    )


def _image_mime_type(filename: str, content_type: str | None) -> str:
    if content_type and content_type.startswith("image/"):
        return content_type
    ext = (filename or "").lower().rsplit(".", 1)[-1] if "." in (filename or "") else ""
    return _IMAGE_MIME_BY_EXT.get(ext, "image/png")


def extract_image_text(
    data: bytes,
    *,
    mime_type: str = "image/png",
    gemini_key: str | None,
    gemini_model: str = gemini_client.DEFAULT_MODEL,
    use_cache: bool = True,
    target_lang_name: str = "Japanisch",
    has_furigana: bool = True,
) -> str:
    """Ein einzelnes Bild per Gemini transkribieren lassen. Braucht immer
    einen Gemini-Key (Bilder haben per Definition keinen Textlayer)."""
    if not gemini_key:
        raise ExtractionError(
            "Für Bild-Import wird ein Gemini-API-Key in den Einstellungen benötigt (Texterkennung im Bild)."
        )
    text = gemini_client.transcribe_image(
        data, gemini_key, mime_type=mime_type, model=gemini_model, use_cache=use_cache,
        target_lang_name=target_lang_name, has_furigana=has_furigana,
    )
    if text is None:
        raise ExtractionError("Texterkennung im Bild fehlgeschlagen (Netzwerk, Quota oder ungültiger Key).")
    return text


def extract_pdf_text(
    data: bytes,
    *,
    gemini_key: str | None,
    gemini_model: str = gemini_client.DEFAULT_MODEL,
    use_cache: bool = True,
    target_lang_name: str = "Japanisch",
    has_furigana: bool = True,
) -> str:
    """Text aus einer PDF-Datei extrahieren, Seite für Seite.

    Seiten mit Textlayer werden direkt ausgelesen (kostenlos, exakt). Seiten
    OHNE Textlayer (Scans) werden nur dann per Gemini-Vision transkribiert,
    wenn ein `gemini_key` vorliegt – sonst bleibt die Seite leer (kein
    harter Abbruch für den Rest des Dokuments, damit ein teilweise
    gescanntes PDF trotzdem so viel wie möglich liefert).
    """
    fitz = _require_fitz()
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 - PyMuPDF wirft diverse eigene Fehlertypen
        raise ExtractionError(f"PDF konnte nicht gelesen werden: {exc}") from exc

    n_pages = doc.page_count
    if n_pages > _MAX_PDF_PAGES:
        logger.warning(
            "pdf_import: PDF hat %d Seiten, verarbeite nur die ersten %d.", n_pages, _MAX_PDF_PAGES,
        )
    pages_text: list[str] = []
    for i in range(min(n_pages, _MAX_PDF_PAGES)):
        page = doc[i]
        text = (page.get_text() or "").strip()
        if len(text) >= _MIN_TEXT_CHARS:
            pages_text.append(text)
            continue
        if not gemini_key:
            logger.info("pdf_import: Seite %d/%d ohne Textlayer, kein Gemini-Key – wird übersprungen.", i + 1, n_pages)
            continue
        pix = page.get_pixmap(dpi=_OCR_RENDER_DPI)
        png_bytes = pix.tobytes("png")
        ocr_text = gemini_client.transcribe_image(
            png_bytes, gemini_key, mime_type="image/png", model=gemini_model, use_cache=use_cache,
            target_lang_name=target_lang_name, has_furigana=has_furigana,
        )
        if ocr_text:
            pages_text.append(ocr_text.strip())
        else:
            logger.warning("pdf_import: OCR für Seite %d/%d fehlgeschlagen, wird übersprungen.", i + 1, n_pages)
    doc.close()
    return "\n\n".join(p for p in pages_text if p)


def extract_text_from_upload(
    data: bytes,
    filename: str,
    content_type: str | None = None,
    *,
    gemini_key: str | None,
    gemini_model: str = gemini_client.DEFAULT_MODEL,
    use_cache: bool = True,
    target_lang_name: str = "Japanisch",
    has_furigana: bool = True,
) -> str:
    """Zentrale Dispatch-Funktion: PDF oder Bild anhand Dateiname/Content-Type
    erkennen und passend extrahieren."""
    kind = _guess_kind(filename, content_type)
    if kind == "pdf":
        return extract_pdf_text(
            data, gemini_key=gemini_key, gemini_model=gemini_model, use_cache=use_cache,
            target_lang_name=target_lang_name, has_furigana=has_furigana,
        )
    mime_type = _image_mime_type(filename, content_type)
    return extract_image_text(
        data, mime_type=mime_type, gemini_key=gemini_key, gemini_model=gemini_model, use_cache=use_cache,
        target_lang_name=target_lang_name, has_furigana=has_furigana,
    )
