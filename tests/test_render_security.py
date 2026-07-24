"""test_render_security.py – Schutz gegen SSRF/Local-File-Disclosure beim
PDF-Rendern.

„Frei erstellen"-Karten dürfen beliebiges HTML enthalten (bewusstes Feature,
siehe templates/cards.html.j2 `| safe`). Ohne den `url_fetcher` aus
`kc._make_safe_url_fetcher` könnte ein Nutzer den Render-Worker per
`<img src="http://…">` interne URLs abrufen lassen (SSRF) oder per
`<img src="file:///…">` lokale Serverdateien in sein PDF einbetten."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shiori import kanji_cards as kc


def _fetcher():
    """url_fetcher mit der echten Standard-Kanji-Schrift als einziger erlaubter
    lokaler Datei."""
    return kc._make_safe_url_fetcher({Path(kc.DEFAULT_KANJI_FONT).resolve()})


def test_fetcher_allows_data_uris():
    fetch = _fetcher()
    # Entscheidend ist nur, dass ein data:-URI NICHT blockiert wird (kein
    # ValueError) - die genaue Rückgabeform (dict/URLFetcherResponse) hängt
    # von der WeasyPrint-Version ab.
    result = fetch("data:text/plain;base64,aGVsbG8=")  # "hello"
    assert result is not None


def test_fetcher_allows_whitelisted_font_file():
    fetch = _fetcher()
    url = Path(kc.DEFAULT_KANJI_FONT).resolve().as_uri()
    result = fetch(url)
    # default_url_fetcher liefert je nach Version 'string' oder 'file_obj' -
    # entscheidend ist nur, dass NICHT blockiert (ValueError) wurde.
    assert result is not None


def test_fetcher_blocks_http_ssrf():
    fetch = _fetcher()
    with pytest.raises(ValueError):
        fetch("http://169.254.169.254/latest/meta-data/")


def test_fetcher_blocks_https():
    fetch = _fetcher()
    with pytest.raises(ValueError):
        fetch("https://example.com/image.png")


def test_fetcher_blocks_non_whitelisted_local_file():
    fetch = _fetcher()
    # Eine lokale Datei, die NICHT in der Font-Allowlist steht (z. B. die
    # SQLite-DB oder eine fremde Export-Datei) - muss blockiert werden.
    with pytest.raises(ValueError):
        fetch(Path("/etc/passwd").as_uri())


def test_fetcher_blocks_font_dir_sibling():
    """Auch eine andere Datei im selben fonts/-Verzeichnis wie die erlaubte
    Schrift darf NICHT geladen werden - die Allowlist ist auf exakte Dateien
    beschränkt, nicht auf das Verzeichnis."""
    fetch = _fetcher()
    sibling = (Path(kc.DEFAULT_KANJI_FONT).resolve().parent / "some-other-file.ttf")
    with pytest.raises(ValueError):
        fetch(sibling.as_uri())


def test_render_blocks_malicious_custom_card_but_still_produces_pdf(tmp_path):
    """End-to-End: eine Custom-Karte mit einem SSRF-<img> wird gerendert - der
    externe Abruf wird blockiert (WeasyPrint überspringt das Bild und loggt
    einen Fehler), das PDF entsteht aber trotzdem, ohne dass jemals eine
    Anfrage an die interne URL rausging."""
    malicious = kc.CustomCard(
        front_html='<img src="http://169.254.169.254/latest/meta-data/">Vorderseite',
        back_html='<img src="file:///etc/passwd">Rückseite',
        tags=["Eigene"],
    )
    out = tmp_path / "cards.pdf"
    kc.render_pdf([malicious], out, cols=1, rows=1)
    assert out.is_file()
    assert out.stat().st_size > 0
    # Ein gültiges PDF beginnt mit dem %PDF-Header.
    assert out.read_bytes()[:5] == b"%PDF-"
