import os

import boto3
from botocore.exceptions import ClientError, ConnectionClosedError, EndpointConnectionError

from backend.pipeline.rate_limit import with_backoff

_RETRYABLE_ERROR_CODES = {
    "InternalError",
    "ServiceUnavailable",
    "SlowDown",
    "RequestTimeout",
}


def _is_transient(e: Exception) -> bool:
    """Only retry on transient network/server-side errors, not on
    application errors like NoSuchBucket, AccessDenied, or NoSuchKey."""
    if isinstance(e, (EndpointConnectionError, ConnectionClosedError)):
        return True
    if isinstance(e, ClientError):
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in _RETRYABLE_ERROR_CODES:
            return True
        status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        if isinstance(status, int) and status >= 500:
            return True
    return False


def get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    )


def upload_image(client, local_path: str, key: str, bucket: str | None = None) -> str:
    bucket = bucket or os.environ["R2_BUCKET"]
    with_backoff(
        lambda: client.upload_file(local_path, bucket, key),
        max_retries=3,
        base_delay=0.5,
        is_retryable=_is_transient,
    )
    return key


def delete_image(client, key: str, bucket: str | None = None) -> None:
    bucket = bucket or os.environ["R2_BUCKET"]
    with_backoff(
        lambda: client.delete_object(Bucket=bucket, Key=key),
        max_retries=3,
        base_delay=0.5,
        is_retryable=_is_transient,
    )
