"""
demo/reset_demo_data.py

시연 반복을 위한 데모 데이터 초기화 스크립트.

지우는 것:
  1. products, product_images 테이블 데이터 전체 (TRUNCATE ... RESTART IDENTITY CASCADE)
     - RESTART IDENTITY: SERIAL id를 1부터 다시 시작. 안 하면 시연할 때마다
       상품 번호가 계속 커져서(예: #47, #48...) 화면이 지저분해짐.
     - CASCADE: product_images가 products를 FK로 참조하므로 함께 비움.
       (참고: product_images FK 자체가 ON DELETE CASCADE라 products만 지워도
       연쇄 삭제되지만, TRUNCATE는 명시적으로 두 테이블을 같이 지정해야 함)
  2. Redis에 캐싱된 상품 목록 캐시
     - GET /products 응답이 캐싱되고 있어서, DB만 비우면 캐시 TTL이 끝날 때까지
       화면에 예전 상품이 계속 보이는 불일치가 생김.

실행 방법 (Bastion에서):
  export DATABASE_URL="postgresql://<user>:<pw>@<host>:5432/<db>"
  export REDIS_URL="redis://<host>:6379/0"
  python3 reset_demo_data.py
"""

import os
import sys

import psycopg2
import redis

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# ⚠️ 확인 필요: 실제 Product Service 코드(main.py)의 캐시 키 이름이 이 패턴과
# 다르면 캐시가 안 지워집니다. 배포된 코드에서 redis 키를 어떻게 짓는지
# (예: "products:list", "products:active" 등) 확인 후 아래 패턴을 맞춰주세요.
CACHE_KEY_PATTERN = "products:*"


def reset_database() -> None:
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE products, product_images RESTART IDENTITY CASCADE;")
    finally:
        conn.close()
    print("[OK] products, product_images 테이블 초기화 완료")


def reset_cache() -> None:
    r = redis.from_url(REDIS_URL)
    keys = r.keys(CACHE_KEY_PATTERN)
    if keys:
        r.delete(*keys)
    print(f"[OK] Redis 캐시 {len(keys)}개 키 삭제 완료 (패턴: {CACHE_KEY_PATTERN})")


def main() -> None:
    if "--yes" not in sys.argv:
        answer = input(
            "정말로 products/product_images 데이터와 Redis 캐시를 전부 삭제하시겠습니까? (y/N): "
        )
        if answer.strip().lower() != "y":
            print("취소했습니다.")
            return

    reset_database()
    reset_cache()


if __name__ == "__main__":
    main()
