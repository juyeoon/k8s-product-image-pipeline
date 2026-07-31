"""NHN Cloud Object Storage(S3 호환) 접근 모듈 (Image Processing Service)."""
import os
import logging

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

OBJECT_STORAGE_ENDPOINT = os.environ["OBJECT_STORAGE_ENDPOINT"]
OBJECT_STORAGE_ACCESS_KEY = os.environ["OBJECT_STORAGE_ACCESS_KEY"]
OBJECT_STORAGE_SECRET_KEY = os.environ["OBJECT_STORAGE_SECRET_KEY"]
OBJECT_STORAGE_BUCKET = os.environ["OBJECT_STORAGE_BUCKET"]

# 실제 NHN Cloud Object Storage 환경에서는 OBJECT_STORAGE_ENDPOINT 자체가 공개적으로
# 접근 가능한 URL이라 별도 값이 필요 없다. 로컬 docker-compose에서는 서비스 간 통신에
# 쓰는 내부 호스트명(예: http://minio:9000)을 브라우저가 그대로 resolve할 수 없으므로,
# 지정된 경우에만 공개 URL 생성 시 이 값으로 대체한다 (미지정 시 기존과 동일하게 동작).
OBJECT_STORAGE_PUBLIC_URL = os.environ.get("OBJECT_STORAGE_PUBLIC_URL", OBJECT_STORAGE_ENDPOINT)

_client = None


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


def download_temp_image(key: str) -> bytes:
    try:
        response = _get_client().get_object(Bucket=OBJECT_STORAGE_BUCKET, Key=key)
        return response["Body"].read()
    except (BotoCoreError, ClientError) as e:
        logger.error(f"event=temp_download_failed key={key} error={e}")
        raise


def upload_public_image(key: str, file_bytes: bytes, content_type: str) -> str:
    """가공된 이미지를 Public Read ACL로 업로드하고 공개 URL을 반환한다.

    상품 이미지는 구매자 전체에게 공개되는 것이 목적이므로 Presigned URL 대신
    단순한 공개 URL을 사용한다.
    """
    try:
        _get_client().put_object(
            Bucket=OBJECT_STORAGE_BUCKET,
            Key=key,
            Body=file_bytes,
            ContentType=content_type,
            ACL="public-read",
        )
    except (BotoCoreError, ClientError) as e:
        logger.error(f"event=public_upload_failed key={key} error={e}")
        raise

    logger.info(f"event=public_upload_succeeded key={key} size_bytes={len(file_bytes)}")
    return f"{OBJECT_STORAGE_PUBLIC_URL.rstrip('/')}/{OBJECT_STORAGE_BUCKET}/{key}"


def delete_temp_image(key: str):
    try:
        _get_client().delete_object(Bucket=OBJECT_STORAGE_BUCKET, Key=key)
        logger.info(f"event=temp_delete_succeeded key={key}")
    except (BotoCoreError, ClientError) as e:
        # 삭제 실패는 처리 결과 자체를 막지 않는다 - cleanup_temp_images.py가 뒤늦게 정리한다.
        logger.warning(f"event=temp_delete_failed key={key} error={e}")
