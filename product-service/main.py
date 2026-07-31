import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, File, UploadFile, HTTPException, Query
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

import db
import cache
import storage
import queue_publisher

logging.basicConfig(level=logging.INFO, format="%(asctime)s level=%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MAX_UPLOAD_SIZE_BYTES = 20 * 1024 * 1024  # 20MB
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 기동 시 DB/Redis/RabbitMQ 연결을 확립한다. 각 모듈이 자체적으로 재시도/백오프를 수행하므로
    # 의존 서비스가 아직 준비되지 않았어도 여기서 크래시하지 않는다.
    db.init_pool()
    cache.init_pool()
    queue_publisher.init_connection()
    yield


app = FastAPI(title="Product Service", lifespan=lifespan)


@app.post("/products", status_code=202)
async def create_product(
    name: str = Form(...),
    price: int = Form(...),
    description: str = Form(""),
    image: UploadFile = File(...),
):
    if image.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="지원하지 않는 이미지 형식입니다 (jpg/png만 허용)")

    file_bytes = await image.read()
    if len(file_bytes) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="이미지 용량은 20MB를 초과할 수 없습니다")

    # db/storage/queue 호출은 동기(blocking) 함수라, 이 코루틴에서 직접 부르면 DB/RabbitMQ
    # 장애로 재연결 재시도(최대 수십 초 블로킹)에 들어갔을 때 이벤트 루프 전체가 멈춰서
    # 다른 모든 요청(예: /health)까지 함께 멈춘다. 스레드풀로 위임해 이벤트 루프를 막지 않는다.
    product_id = await run_in_threadpool(db.insert_draft_product, name, price, description)
    logger.info(f"event=status_transition product_id={product_id} to=draft")

    temp_image_key = await run_in_threadpool(storage.upload_temp_image, file_bytes, image.content_type)

    await run_in_threadpool(queue_publisher.publish_image_processing_task, product_id, temp_image_key)

    return {"product_id": product_id, "status": "draft"}


@app.get("/products")
def list_products(status: str | None = Query(default=None)):
    # status=all: 발표용 Web UI 판매자 화면에서, 브라우저 세션과 무관하게(다른 곳에서
    # curl로 등록한 것 포함) 등록된 모든 상품의 상태 전이를 보여주기 위한 조회 전용 옵션.
    # 기존 기본 동작(구매자용 active만 조회 + 캐싱)은 그대로 유지된다.
    # 일반 def로 선언하면 FastAPI/Starlette가 자동으로 스레드풀에서 실행해주므로,
    # 내부에서 부르는 동기 DB/Redis 호출이 이벤트 루프를 막지 않는다.
    if status == "all":
        return db.list_all_products()

    cached = cache.get_active_products_cache()
    if cached is not None:
        return cached

    products = db.list_active_products()
    cache.set_active_products_cache(products)
    return products


@app.get("/products/{product_id}")
def get_product(product_id: int):
    product = db.get_product(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return product


@app.get("/health")
def health():
    db_ok = db.health_check()
    redis_ok = cache.health_check()
    if db_ok and redis_ok:
        return {"status": "ok"}
    return JSONResponse(status_code=503, content={"status": "unhealthy", "db": db_ok, "redis": redis_ok})
