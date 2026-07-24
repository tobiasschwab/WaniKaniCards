#!/usr/bin/env python3
"""storage.py – Speicher für generierte PDFs/APKGs.

Lokaler Disk-Speicher (Standard, Zero-Config für Demo/Entwicklung/Self-
Hosting mit einem einzelnen App-Container) ODER Object Storage (S3-
kompatibel, z. B. AWS S3 oder selbst gehostetes MinIO) für den Multi-User-
Betrieb mit mehreren App-/Worker-Instanzen, die sich kein gemeinsames
Dateisystem teilen.

Umschaltung rein über Umgebungsvariablen (siehe `is_object_storage_enabled()`)
– der Rest von webapp.py kennt nur diese Modul-Funktionen, nicht die
Speicherimplementierung dahinter.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_S3_BUCKET = os.environ.get("S3_BUCKET")
_S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL")  # für MinIO/selbst gehostetes S3
_S3_REGION = os.environ.get("S3_REGION", "us-east-1")

_s3_client: Any = None


def is_object_storage_enabled() -> bool:
    """Object Storage aktiv, sobald ein Bucket-Name gesetzt ist. Ohne
    S3_BUCKET bleibt alles beim lokalen Disk-Speicher (Standard)."""
    return bool(_S3_BUCKET)


def _get_s3_client() -> Any:
    global _s3_client
    if _s3_client is None:
        import boto3  # nur importieren, wenn tatsächlich gebraucht

        _s3_client = boto3.client(
            "s3", endpoint_url=_S3_ENDPOINT_URL, region_name=_S3_REGION,
        )
    return _s3_client


def save_output(output_dir: Path, key: str, data: bytes) -> None:
    """Erzeugte Datei (PDF/APKG) speichern – `key` ist z. B. `<job_id>.pdf`."""
    if is_object_storage_enabled():
        _get_s3_client().put_object(Bucket=_S3_BUCKET, Key=key, Body=data)
    else:
        (output_dir / key).write_bytes(data)


def read_output(output_dir: Path, key: str) -> bytes | None:
    """`None`, wenn die Datei nicht existiert (weder Disk noch S3) – fail-soft
    wie der Rest des Projekts, kein Exception-Durchreichen an den Aufrufer."""
    if is_object_storage_enabled():
        try:
            resp = _get_s3_client().get_object(Bucket=_S3_BUCKET, Key=key)
            return resp["Body"].read()
        except _get_s3_client().exceptions.NoSuchKey:
            return None
        except Exception:  # noqa: BLE001 - z. B. Netzwerkfehler, Bucket nicht erreichbar
            return None
    path = output_dir / key
    return path.read_bytes() if path.is_file() else None


def output_exists(output_dir: Path, key: str) -> bool:
    if is_object_storage_enabled():
        try:
            _get_s3_client().head_object(Bucket=_S3_BUCKET, Key=key)
            return True
        except Exception:  # noqa: BLE001
            return False
    return (output_dir / key).is_file()


def delete_output(output_dir: Path, key: str) -> None:
    if is_object_storage_enabled():
        try:
            _get_s3_client().delete_object(Bucket=_S3_BUCKET, Key=key)
        except Exception:  # noqa: BLE001
            pass
    else:
        (output_dir / key).unlink(missing_ok=True)


def generate_download_url(key: str, *, filename: str, expires_in: int = 300) -> str | None:
    """Signierte, zeitlich begrenzte Download-URL – nur wenn Object Storage
    aktiv ist. `None` bedeutet: der Aufrufer soll die Datei stattdessen
    direkt per `send_file()` vom lokalen Disk ausliefern."""
    if not is_object_storage_enabled():
        return None
    return _get_s3_client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": _S3_BUCKET,
            "Key": key,
            "ResponseContentDisposition": f'attachment; filename="{filename}"',
        },
        ExpiresIn=expires_in,
    )
