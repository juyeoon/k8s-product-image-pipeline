"""
테이블 소유권 (향후 서비스별 DB 분리 대비):
- products: Product Service 소유
  (Image Processing Service는 db.py의 update_product_status() 단일 함수를 통해서만
   상태를 변경한다. 다른 곳에서 직접 UPDATE 문을 실행하지 않는다.)
- product_images: Image Processing Service 소유 (읽기/쓰기)
"""
from enum import Enum


class ProductStatus(str, Enum):
    DRAFT = "draft"
    PROCESSING = "processing"
    ACTIVE = "active"
    REJECTED = "rejected"


SUPPORTED_IMAGE_FORMATS = {"JPEG", "PNG"}
MIN_DIMENSION_PX = 500

RESIZE_SPECS = {
    "thumbnail": 200,
    "detail": 800,
    "zoom": 1600,
}
