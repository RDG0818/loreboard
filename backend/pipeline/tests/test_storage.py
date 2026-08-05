import os
from unittest.mock import MagicMock
from backend.pipeline import storage


def test_upload_image_calls_upload_file_with_expected_args(monkeypatch):
    monkeypatch.setenv("R2_BUCKET", "loreboard-assets")
    client = MagicMock()

    key = storage.upload_image(client, "/tmp/local.jpg", "images/local.jpg")

    client.upload_file.assert_called_once_with("/tmp/local.jpg", "loreboard-assets", "images/local.jpg")
    assert key == "images/local.jpg"


def test_upload_image_uses_explicit_bucket_over_env(monkeypatch):
    monkeypatch.setenv("R2_BUCKET", "loreboard-assets")
    client = MagicMock()

    storage.upload_image(client, "/tmp/local.jpg", "images/local.jpg", bucket="other-bucket")

    client.upload_file.assert_called_once_with("/tmp/local.jpg", "other-bucket", "images/local.jpg")
