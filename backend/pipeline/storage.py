import os

import boto3

from backend.pipeline.rate_limit import with_backoff


def get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    )


def upload_image(client, local_path: str, key: str, bucket: str | None = None) -> str:
    bucket = bucket or os.environ["R2_BUCKET"]
    with_backoff(lambda: client.upload_file(local_path, bucket, key), max_retries=3, base_delay=0.5)
    return key


def delete_image(client, key: str, bucket: str | None = None) -> None:
    bucket = bucket or os.environ["R2_BUCKET"]
    with_backoff(lambda: client.delete_object(Bucket=bucket, Key=key), max_retries=3, base_delay=0.5)
