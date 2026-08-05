"""
발표용 데모 이미지 생성 스크립트.

Pillow가 설치된 환경에서 실행해야 하므로, 이 리포지토리에서는 이미 Pillow가 들어있는
image-processing-service 이미지로 실행하는 것을 권장한다 (run_demo.sh가 자동으로 해준다):

    docker run --rm -v "$(pwd)/demo:/demo" \
      k8s-product-image-pipeline-image-processing-service \
      python /demo/generate_demo_images.py

노이즈 이미지를 쓰는 이유: 단색/그라디언트 이미지는 JPEG 압축이 매우 잘 되어 실제
리사이징 부하가 거의 눈에 띄지 않는다. 순수 랜덤 노이즈는 압축이 잘 안 되어 원본 파일
용량이 크고, Pillow의 LANCZOS 리사이징 연산량도 사실적인 사진에 가깝게 나온다.
"""
import os

from PIL import Image

IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")

# (파일명, 한 변 픽셀 크기) - 20MB 업로드 제한 안에서 실측으로 정한 크기(약 18MB, 처리에
# 약 3~4초 소요). 너무 작으면 처리가 순식간에 끝나 버려 큐 백로그가 눈에 보이지 않는다.
BACKLOG_SPECS = [(f"demo_backlog_{i}.jpg", 4600) for i in range(1, 6)]
REJECT_SPEC = ("demo_reject.jpg", 100)  # 최소 해상도(500px) 미달 -> rejected 시연용


def _generate_noise_jpeg(path: str, side_px: int):
    if os.path.exists(path):
        print(f"skip (already exists): {path}")
        return
    data = os.urandom(side_px * side_px * 3)
    image = Image.frombytes("RGB", (side_px, side_px), data)
    image.save(path, format="JPEG", quality=90)
    size_mb = os.path.getsize(path) / 1024 / 1024
    print(f"generated: {path} ({side_px}x{side_px}, {size_mb:.1f}MB)")


def main():
    os.makedirs(IMAGES_DIR, exist_ok=True)

    for filename, side_px in BACKLOG_SPECS:
        _generate_noise_jpeg(os.path.join(IMAGES_DIR, filename), side_px)

    filename, side_px = REJECT_SPEC
    _generate_noise_jpeg(os.path.join(IMAGES_DIR, filename), side_px)


if __name__ == "__main__":
    main()
