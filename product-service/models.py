"""
테이블 소유권 (향후 서비스별 DB 분리 대비):
- products: Product Service 소유 (읽기/쓰기)
- product_images: Image Processing Service 소유
  (Product Service는 상세/목록 조회 시 읽기 전용 JOIN만 수행하며, 쓰기 작업을 하지 않는다)
"""
from enum import Enum


class ProductStatus(str, Enum):
    DRAFT = "draft"
    PROCESSING = "processing"
    ACTIVE = "active"
    REJECTED = "rejected"
