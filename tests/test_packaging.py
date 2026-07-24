"""test_packaging.py – Schutz gegen einen realen Bug: nach dem Aufteilen von
webapp.py in Blueprints (services.py/srs_api.py/cards_api.py/jobs_api.py)
fehlten die neuen Module zunächst in der COPY-Zeile des Dockerfiles, wodurch
das Docker-Image zwar baute, der Container aber beim Import von webapp.py
abstürzte. Die normale Test-Suite fängt das nicht, weil sie lokal (nicht im
Container) läuft.

Seit der Umstrukturierung in das `shiori`-Package (statt einzelner
Top-Level-Module) kopiert das Dockerfile das komplette Package in EINEM
COPY-Befehl (`COPY shiori/ ./shiori/`) – die ursprüngliche Bug-Klasse
("ein neues Modul in der COPY-Zeile vergessen") ist damit strukturell
ausgeschlossen. Dieser Test hält trotzdem fest, dass genau dieser
COPY-Befehl (und keine Rückkehr zu einzeln aufgezählten Dateien) im
Dockerfile steht, und dass es tatsächlich kein Top-Level-`.py`-Modul mehr
im Projekt-Root gibt, das versehentlich am Package vorbei landen könnte."""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_no_stray_top_level_python_modules():
    """Alle Anwendungs-Module gehören ins `shiori`-Package - ein `.py` direkt
    im Projekt-Root würde von `COPY shiori/ ./shiori/` NICHT erfasst und im
    Container fehlen, ohne dass der Build das anzeigt."""
    stray = {p.name for p in _ROOT.glob("*.py")}
    assert not stray, (
        f"Diese Module liegen fälschlich im Projekt-Root statt im "
        f"shiori-Package und würden im Docker-Image fehlen: {sorted(stray)}"
    )


def test_dockerfile_copies_the_whole_shiori_package():
    """Das Dockerfile muss das komplette Package in einem Rutsch kopieren -
    eine Rückkehr zu einzeln aufgezählten Dateinamen wäre wieder anfällig für
    das ursprüngliche "Modul vergessen"-Problem."""
    dockerfile = (_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY shiori/ ./shiori/" in dockerfile or "COPY shiori/ ./shiori" in dockerfile, (
        "Dockerfile sollte das gesamte shiori/-Package per COPY einbinden, "
        "nicht einzelne Dateien auflisten."
    )
