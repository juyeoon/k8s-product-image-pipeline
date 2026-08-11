#!/usr/bin/env bash
# 발표용 데모 스크립트.
#
# 1) 고해상도 이미지 5장을 연속 업로드한다. Image Processing Service는
#    RabbitMQ에서 prefetch_count=1로 메시지를 하나씩만 처리하므로, 이미지 1장 처리에
#    약 3~4초가 걸리는 이 이미지들을 동시에 올리면 여러 상품이 몇 초~수십 초 동안
#    "processing" 상태로 큐에 쌓여 있는 모습을 Web UI에서 실시간으로 볼 수 있다.
#    (인위적인 지연이 아니라 실제 리사이징 부하로 자연스럽게 걸리는 시간이다.)
# 2) 저해상도 이미지 1장을 업로드해 rejected 시연도 함께 보여준다.
# 3) 터미널에서도 각 상품의 상태 변화를 1초 간격으로 출력해, Web UI 화면과 함께
#    진행 상황을 설명할 수 있게 한다.
set -euo pipefail

PRODUCT_SERVICE_URL="${PRODUCT_SERVICE_URL:-http://localhost:8000}"
DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGES_DIR="$DEMO_DIR/images"
WATCH_SECONDS="${WATCH_SECONDS:-30}"

if [ ! -d "$IMAGES_DIR" ] || [ -z "$(ls -A "$IMAGES_DIR" 2>/dev/null)" ]; then
  echo "데모 이미지가 없습니다. 먼저 아래 명령으로 생성하세요:"
  echo "  docker run --rm -v \"\$(pwd)/demo/local:/demo\" k8s-product-image-pipeline-image-processing-service python /demo/generate_demo_images.py"
  exit 1
fi

PRODUCT_IDS=()

upload() {
  local name="$1" price="$2" image_path="$3"
  local response product_id
  response=$(curl -s -X POST "$PRODUCT_SERVICE_URL/products" \
    -F "name=$name" -F "price=$price" -F "description=demo" \
    -F "image=@${image_path}")
  product_id=$(echo "$response" | sed -E 's/.*"product_id":([0-9]+).*/\1/')
  echo "  -> 등록됨: $name (product_id=$product_id, $(basename "$image_path"))"
  PRODUCT_IDS+=("$product_id")
}

echo "=== 1) 고해상도 이미지 5장 연속 업로드 (큐 백로그 시연) ==="
for i in 1 2 3 4 5; do
  upload "Demo Backlog $i" $((10000 * i)) "$IMAGES_DIR/demo_backlog_$i.jpg"
done

echo
echo "=== 2) 저해상도 이미지 업로드 (반려 시연) ==="
upload "Demo Reject" 5000 "$IMAGES_DIR/demo_reject.jpg"

echo
echo "=== Web UI(http://localhost:8080) 판매자 화면에서 배지 색이 바뀌는 걸 함께 보세요 ==="
echo "=== 상태 변화 실시간 관찰 (${WATCH_SECONDS}초, 1초 간격) ==="
for _ in $(seq 1 "$WATCH_SECONDS"); do
  line=""
  for pid in "${PRODUCT_IDS[@]}"; do
    status=$(curl -s "$PRODUCT_SERVICE_URL/products/$pid" | sed -E 's/.*"status":"([a-z]+)".*/\1/')
    line="$line #$pid:$status"
  done
  echo "$line"
  sleep 1
done
