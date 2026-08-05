import os
from unittest.mock import MagicMock
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
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


def test_delete_image_calls_delete_object_with_expected_args(monkeypatch):
    monkeypatch.setenv("R2_BUCKET", "loreboard-assets")
    client = MagicMock()

    storage.delete_image(client, "images/local.jpg")

    client.delete_object.assert_called_once_with(Bucket="loreboard-assets", Key="images/local.jpg")


def test_delete_image_uses_explicit_bucket_over_env(monkeypatch):
    monkeypatch.setenv("R2_BUCKET", "loreboard-assets")
    client = MagicMock()

    storage.delete_image(client, "images/local.jpg", bucket="other-bucket")

    client.delete_object.assert_called_once_with(Bucket="other-bucket", Key="images/local.jpg")


def _client_error(code, status=500):
    return ClientError(
        error_response={"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}},
        operation_name="PutObject",
    )


def test_upload_image_retries_on_transient_service_error(monkeypatch):
    monkeypatch.setenv("R2_BUCKET", "loreboard-assets")
    monkeypatch.setattr("backend.pipeline.rate_limit.time.sleep", lambda s: None)
    client = MagicMock()
    client.upload_file.side_effect = [_client_error("ServiceUnavailable"), None]

    key = storage.upload_image(client, "/tmp/local.jpg", "images/local.jpg")

    assert key == "images/local.jpg"
    assert client.upload_file.call_count == 2


def test_upload_image_retries_on_endpoint_connection_error(monkeypatch):
    monkeypatch.setenv("R2_BUCKET", "loreboard-assets")
    monkeypatch.setattr("backend.pipeline.rate_limit.time.sleep", lambda s: None)
    client = MagicMock()
    client.upload_file.side_effect = [EndpointConnectionError(endpoint_url="https://r2.example.com"), None]

    storage.upload_image(client, "/tmp/local.jpg", "images/local.jpg")

    assert client.upload_file.call_count == 2


def test_upload_image_does_not_retry_on_access_denied(monkeypatch):
    """Non-transient, permission-level errors must propagate immediately."""
    monkeypatch.setenv("R2_BUCKET", "loreboard-assets")
    client = MagicMock()
    client.upload_file.side_effect = _client_error("AccessDenied", status=403)

    with pytest.raises(ClientError):
        storage.upload_image(client, "/tmp/local.jpg", "images/local.jpg")

    assert client.upload_file.call_count == 1


def test_upload_image_does_not_retry_on_no_such_bucket(monkeypatch):
    """Non-transient, not-found errors must propagate immediately."""
    monkeypatch.setenv("R2_BUCKET", "loreboard-assets")
    client = MagicMock()
    client.upload_file.side_effect = _client_error("NoSuchBucket", status=404)

    with pytest.raises(ClientError):
        storage.upload_image(client, "/tmp/local.jpg", "images/local.jpg")

    assert client.upload_file.call_count == 1


def test_delete_image_retries_on_transient_service_error(monkeypatch):
    monkeypatch.setenv("R2_BUCKET", "loreboard-assets")
    monkeypatch.setattr("backend.pipeline.rate_limit.time.sleep", lambda s: None)
    client = MagicMock()
    client.delete_object.side_effect = [_client_error("SlowDown"), None]

    storage.delete_image(client, "images/local.jpg")

    assert client.delete_object.call_count == 2


def test_delete_image_does_not_retry_on_no_such_key(monkeypatch):
    """Non-transient, not-found errors must propagate immediately."""
    monkeypatch.setenv("R2_BUCKET", "loreboard-assets")
    client = MagicMock()
    client.delete_object.side_effect = _client_error("NoSuchKey", status=404)

    with pytest.raises(ClientError):
        storage.delete_image(client, "images/local.jpg")

    assert client.delete_object.call_count == 1
