"""
temp/ 임시 이미지 정리 스크립트.

Object Storage의 temp/ 경로를 스캔해서 업로드 시각이 24시간 이상 지난 파일을 삭제한다.
실행할 때마다 한 번 스캔하고 종료하는 일회성 스크립트로, K8s CronJob으로 주기 실행된다.

DLQ로 넘어가 처리되지 못한 메시지의 temp/ 원본은 Image Processing Service가 지우지 않으므로,
이 스크립트가 뒤늦게 정리한다.
"""
import os
import logging
from datetime import datetime, timedelta, timezone

import boto3
from botocore.config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s level=%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OBJECT_STORAGE_ENDPOINT = os.environ["OBJECT_STORAGE_ENDPOINT"]
OBJECT_STORAGE_ACCESS_KEY = os.environ["OBJECT_STORAGE_ACCESS_KEY"]
OBJECT_STORAGE_SECRET_KEY = os.environ["OBJECT_STORAGE_SECRET_KEY"]
OBJECT_STORAGE_BUCKET = os.environ["OBJECT_STORAGE_BUCKET"]

TEMP_PREFIX = "temp/"
MAX_AGE = timedelta(hours=24)


def get_client():
    return boto3.client(
        "s3",
        endpoint_url=OBJECT_STORAGE_ENDPOINT,
        aws_access_key_id=OBJECT_STORAGE_ACCESS_KEY,
        aws_secret_access_key=OBJECT_STORAGE_SECRET_KEY,
        config=Config(signature_version="s3v4"),
    )


def cleanup_temp_images():
    client = get_client()
    cutoff = datetime.now(timezone.utc) - MAX_AGE

    scanned = 0
    deleted = 0
    paginator = client.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=OBJECT_STORAGE_BUCKET, Prefix=TEMP_PREFIX):
        for obj in page.get("Contents", []):
            scanned += 1
            if obj["LastModified"] < cutoff:
                client.delete_object(Bucket=OBJECT_STORAGE_BUCKET, Key=obj["Key"])
                deleted += 1
                logger.info(f"event=temp_file_deleted key={obj['Key']} last_modified={obj['LastModified']}")

    logger.info(f"event=cleanup_completed scanned={scanned} deleted={deleted}")


if __name__ == "__main__":
    cleanup_temp_images()
