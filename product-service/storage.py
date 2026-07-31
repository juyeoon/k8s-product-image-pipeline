"""
NHN Cloud Object Storage(S3 호환) 업로드 모듈 (Product Service).

Product Service와 Image Processing Service는 서로 다른 Pod이기 때문에 로컬 디스크를
공유할 수 없다. 원본 이미지는 반드시 Object Storage의 temp/ 경로를 경유한다.
"""
import os
import uuid
import logging

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

OBJECT_STORAGE_ENDPOINT = os.environ["OBJECT_STORAGE_ENDPOINT"]
OBJECT_STORAGE_ACCESS_KEY = os.environ["OBJECT_STORAGE_ACCESS_KEY"]
OBJECT_STORAGE_SECRET_KEY = os.environ["OBJECT_STORAGE_SECRET_KEY"]
OBJECT_STORAGE_BUCKET = os.environ["OBJECT_STORAGE_BUCKET"]

_client = None

EXTENSION_BY_CONTENT_TYPE = {
    "image/jpeg": "jpg",
    "image/png": "png",
}


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=OBJECT_STORAGE_ENDPOINT,
            aws_access_key_id=OBJECT_STORAGE_ACCESS_KEY,
            aws_secret_access_key=OBJECT_STORAGE_SECRET_KEY,
            config=Config(signature_version="s3v4"),
        )
    return _client


def upload_temp_image(file_bytes: bytes, content_type: str) -> str:
    """원본 이미지를 temp/ 경로에 업로드하고 object key를 반환한다."""
    ext = EXTENSION_BY_CONTENT_TYPE.get(content_type, "jpg")
    key = f"temp/{uuid.uuid4()}_original.{ext}"

    try:
        _get_client().put_object(
            Bucket=OBJECT_STORAGE_BUCKET,
            Key=key,
            Body=file_bytes,
            ContentType=content_type,
        )
    except (BotoCoreError, ClientError) as e:
        logger.error(f"event=temp_upload_failed key={key} error={e}")
        raise

    logger.info(f"event=temp_upload_succeeded key={key} size_bytes={len(file_bytes)}")
    return key
