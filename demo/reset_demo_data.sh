#!/usr/bin/env bash
# 로컬 데모 데이터 초기화 스크립트.
#
# docker compose 스택은 그대로 띄워둔 채(재기동 없이) 데이터만 비운다. 완전히 처음
# 상태로 되돌리고 싶다면(예: 볼륨 자체가 이상하거나 스키마를 다시 만들고 싶을 때) README의
# "발표 전 데이터 초기화" 섹션에 있는 `docker compose down -v && docker compose up --build -d`를
# 대신 사용한다.
#
# 비우는 대상:
#   1) Postgres: products, product_images 테이블 (TRUNCATE ... RESTART IDENTITY로 id도 1부터 재시작)
#   2) Redis: products:active 캐시 키
#   3) MinIO: product-images 버킷의 temp/, products/ 아래 객체 전부
set -euo pipefail

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$DEMO_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "=== 1) Postgres: products / product_images 비우는 중 ==="
docker compose exec -T postgres psql -U app -d productdb \
  -c "TRUNCATE products, product_images RESTART IDENTITY CASCADE;"

echo "=== 2) Redis: products:active 캐시 삭제 ==="
docker compose exec -T redis redis-cli DEL products:active

echo "=== 3) MinIO: product-images/temp/, product-images/products/ 비우는 중 ==="
docker compose exec -T minio sh -c '
  mc alias set local http://localhost:9000 minioadmin minioadmin >/dev/null 2>&1
  mc rm --recursive --force local/product-images/temp/ >/dev/null 2>&1 || true
  mc rm --recursive --force local/product-images/products/ >/dev/null 2>&1 || true
'

echo
echo "=== 확인: GET /products?status=all ==="
PRODUCT_SERVICE_URL="${PRODUCT_SERVICE_URL:-http://localhost:8000}"
curl -s "$PRODUCT_SERVICE_URL/products?status=all"
echo
echo "위 결과가 빈 배열([])이면 초기화 완료. 이제 bash demo/run_demo.sh를 실행하면 됩니다."
