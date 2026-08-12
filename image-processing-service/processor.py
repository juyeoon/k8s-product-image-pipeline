"""이미지 검수(룰 기반) + 리사이징 로직. 실제 Pillow 연산을 사용해 자연스러운 CPU/메모리 부하를 낸다."""
import io
import uuid
import logging

from PIL import Image

from models import SUPPORTED_IMAGE_FORMATS, MIN_DIMENSION_PX, RESIZE_SPECS
import storage

logger = logging.getLogger(__name__)


def inspect_image(file_bytes: bytes):
    """룰 기반 검수. 통과 시 (True, None, PIL.Image), 실패 시 (False, 사유, None)을 반환한다."""
    try:
        image = Image.open(io.BytesIO(file_bytes))
        image.load()
    except Exception as e:
        return False, f"이미지 파일을 열 수 없습니다: {e}", None

    if image.format not in SUPPORTED_IMAGE_FORMATS:
        return False, f"지원하지 않는 이미지 형식입니다: {image.format}", None

    width, height = image.size
    if width < MIN_DIMENSION_PX or height < MIN_DIMENSION_PX:
        return False, f"이미지 해상도가 최소 기준({MIN_DIMENSION_PX}px)에 미달합니다: {width}x{height}", None

    # TODO(LLM 검수 연동 지점): 룰 기반 검수를 통과한 이미지를 대상으로 여기서 비전 LLM API를
    # 호출해 상품 이미지로 부적절한 콘텐츠인지, 상품 사진 품질이 적절한지 등을 추가로 판단할 수 있다.
    # 예: reject_reason = call_vision_llm_for_content_check(file_bytes) 후 실패 시 (False, reject_reason, None) 반환.
    # 현재는 스펙 범위 밖(13번 항목)이라 호출하지 않고 룰 기반 결과만 반환한다.

    return True, None, image


def resize_and_upload(product_id: int, image: Image.Image):
    """thumbnail/detail/zoom 3종으로 리사이징 후 Object Storage에 업로드하고 (size_type, url) 목록을 반환한다."""
    rgb_image = image.convert("RGB")
    width, height = rgb_image.size
    results = []

    for size_type, max_dimension in RESIZE_SPECS.items():
        # Image.thumbnail()은 축소만 하고 원본보다 작은 목표 크기는 확대하지 않으므로,
        # 원본이 목표(특히 zoom=1600px)보다 작을 때도 실제로 리사이징되도록 직접 배율을 계산한다.
        scale = max_dimension / max(width, height)
        new_size = (round(width * scale), round(height * scale))
        resized = rgb_image.resize(new_size, Image.LANCZOS)

        buffer = io.BytesIO()
        resized.save(buffer, format="JPEG", quality=85)
        file_bytes = buffer.getvalue()

        # 원본 파일명 노출 방지 및 URL 추측 방지를 위해 UUID로 파일명 생성
        key = f"products/{product_id}/{uuid.uuid4()}_{size_type}.jpg"
        url = storage.upload_public_image(key, file_bytes, "image/jpeg")
        results.append((size_type, url))
        logger.info(f"event=image_resized product_id={product_id} size_type={size_type} url={url}")

    return results
