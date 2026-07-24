"""Tests für storage.py – lokaler Disk-Speicher (Default) und S3/MinIO
(gemockt über moto, kein Live-Netzwerk nötig)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from shiori import storage


# --------------------------------------------------------------------------- #
# Lokaler Disk-Speicher (Default, kein S3_BUCKET gesetzt)
# --------------------------------------------------------------------------- #

def test_object_storage_disabled_without_bucket(monkeypatch):
    monkeypatch.setattr(storage, "_S3_BUCKET", None)
    assert storage.is_object_storage_enabled() is False


def test_local_save_and_read_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "_S3_BUCKET", None)
    storage.save_output(tmp_path, "job1.pdf", b"pdf-bytes")
    assert storage.read_output(tmp_path, "job1.pdf") == b"pdf-bytes"


def test_local_read_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "_S3_BUCKET", None)
    assert storage.read_output(tmp_path, "missing.pdf") is None


def test_local_output_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "_S3_BUCKET", None)
    assert storage.output_exists(tmp_path, "job1.pdf") is False
    storage.save_output(tmp_path, "job1.pdf", b"x")
    assert storage.output_exists(tmp_path, "job1.pdf") is True


def test_local_delete_output(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "_S3_BUCKET", None)
    storage.save_output(tmp_path, "job1.pdf", b"x")
    storage.delete_output(tmp_path, "job1.pdf")
    assert storage.output_exists(tmp_path, "job1.pdf") is False


def test_local_delete_missing_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "_S3_BUCKET", None)
    storage.delete_output(tmp_path, "missing.pdf")  # darf nicht crashen


def test_generate_download_url_returns_none_without_object_storage(monkeypatch):
    monkeypatch.setattr(storage, "_S3_BUCKET", None)
    assert storage.generate_download_url("job1.pdf", filename="cards.pdf") is None


# --------------------------------------------------------------------------- #
# S3/MinIO (moto-gemockt)
# --------------------------------------------------------------------------- #

@pytest.fixture
def s3_bucket(monkeypatch):
    """S3 aktivieren + einen gemockten Bucket bereitstellen (moto fängt alle
    boto3-Aufrufe ab, kein echtes AWS/Netzwerk nötig)."""
    from moto import mock_aws

    monkeypatch.setattr(storage, "_S3_BUCKET", "shiori-test-bucket")
    monkeypatch.setattr(storage, "_s3_client", None)
    with mock_aws():
        import boto3
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="shiori-test-bucket")
        yield client
    monkeypatch.setattr(storage, "_s3_client", None)


def test_s3_enabled_with_bucket_set(s3_bucket):
    assert storage.is_object_storage_enabled() is True


def test_s3_save_and_read_roundtrip(s3_bucket, tmp_path):
    storage.save_output(tmp_path, "job1.pdf", b"pdf-bytes")
    assert storage.read_output(tmp_path, "job1.pdf") == b"pdf-bytes"
    # Lokales Disk-Verzeichnis bleibt unberührt - Daten liegen nur in S3.
    assert not (tmp_path / "job1.pdf").exists()


def test_s3_read_missing_returns_none(s3_bucket, tmp_path):
    assert storage.read_output(tmp_path, "missing.pdf") is None


def test_s3_output_exists(s3_bucket, tmp_path):
    assert storage.output_exists(tmp_path, "job1.pdf") is False
    storage.save_output(tmp_path, "job1.pdf", b"x")
    assert storage.output_exists(tmp_path, "job1.pdf") is True


def test_s3_delete_output(s3_bucket, tmp_path):
    storage.save_output(tmp_path, "job1.pdf", b"x")
    storage.delete_output(tmp_path, "job1.pdf")
    assert storage.output_exists(tmp_path, "job1.pdf") is False


def test_s3_generate_download_url_returns_signed_url(s3_bucket, tmp_path):
    storage.save_output(tmp_path, "job1.pdf", b"x")
    url = storage.generate_download_url("job1.pdf", filename="cards.pdf")
    assert url is not None
    assert "job1.pdf" in url
