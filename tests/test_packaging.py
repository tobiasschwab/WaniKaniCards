"""test_packaging.py – Schutz gegen einen realen Bug: nach dem Aufteilen von
webapp.py in Blueprints (services.py/srs_api.py/cards_api.py/jobs_api.py)
fehlten die neuen Module zunächst in der COPY-Zeile des Dockerfiles, wodurch
das Docker-Image zwar baute, der Container aber beim Import von webapp.py
abstürzte. Die normale Test-Suite fängt das nicht, weil sie lokal (nicht im
Container) läuft. Dieser Test hält Dockerfile und tatsächliche Modulliste
synchron."""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _local_top_level_modules() -> set[str]:
    """Alle .py-Dateien im Projekt-Root (Top-Level-Module, keine Pakete/Tests)."""
    return {p.name for p in _ROOT.glob("*.py")}


def _dockerfile_copied_modules() -> set[str]:
    """Alle in der/den COPY-Anweisung(en) des Dockerfiles namentlich genannten
    .py. Backslash-Zeilenfortsetzungen werden zuvor zu einer logischen Zeile
    zusammengefasst, da eine COPY-Anweisung über mehrere physische Zeilen
    laufen kann."""
    dockerfile = (_ROOT / "Dockerfile").read_text(encoding="utf-8")
    logical = dockerfile.replace("\\\n", " ")
    copied: set[str] = set()
    for line in logical.splitlines():
        if line.strip().startswith("COPY"):
            copied.update(re.findall(r"[A-Za-z0-9_]+\.py", line))
    return copied


def test_all_local_modules_are_copied_into_docker_image():
    """Jedes Top-Level-Modul muss ins Image kopiert werden – sonst crasht der
    Container beim Import, obwohl der Build durchläuft (siehe Modul-Docstring)."""
    missing = _local_top_level_modules() - _dockerfile_copied_modules()
    assert not missing, (
        "Diese Module fehlen in der COPY-Zeile des Dockerfiles und würden im "
        f"Container fehlen: {sorted(missing)}"
    )
