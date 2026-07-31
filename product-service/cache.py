"""Redis 캐시 접근 모듈 (Product Service). active 상품 목록만 캐싱한다."""
import os
import json
import time
import logging

import redis

logger = logging.getLogger(__name__)

REDIS_URL = os.environ["REDIS_URL"]
ACTIVE_PRODUCTS_KEY = "products:active"
CACHE_TTL_SECONDS = 30

MAX_RETRIES = 10
INITIAL_BACKOFF_SECONDS = 2
MAX_BACKOFF_SECONDS = 60

_client = None


def _connect_with_retry():
    attempt = 0
    delay = INITIAL_BACKOFF_SECONDS
    while True:
        try:
            client = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=3)
            client.ping()
            logger.info("event=redis_connected")
            return client
        except redis.exceptions.RedisError as e:
            attempt += 1
            if attempt > MAX_RETRIES:
                logger.error(f"event=redis_connect_failed attempt={attempt} error={e}")
                raise
            logger.warning(f"event=redis_connect_retry attempt={attempt} delay={delay}s error={e}")
            time.sleep(delay)
            delay = min(delay * 2, MAX_BACKOFF_SECONDS)


def init_pool():
    global _client
    _client = _connect_with_retry()


def _get_client():
    global _client
    if _client is None:
        _client = _connect_with_retry()
    return _client


def health_check() -> bool:
    """K8s Liveness/Readiness Probe용 - 재시도/백오프 없이 짧은 타임아웃으로 1회만 확인한다.

    _get_client()가 클라이언트 재생성을 트리거하면 _connect_with_retry()의 최대 10회,
    백오프 최대 60초 대기에 그대로 물릴 수 있어 Probe 응답에는 부적합하다.
    """
    try:
        redis.Redis.from_url(REDIS_URL, socket_connect_timeout=2).ping()
        return True
    except redis.exceptions.RedisError as e:
        logger.error(f"event=redis_health_check_failed error={e}")
        return False


def get_active_products_cache():
    global _client
    try:
        raw = _get_client().get(ACTIVE_PRODUCTS_KEY)
        return json.loads(raw) if raw else None
    except redis.exceptions.RedisError as e:
        logger.warning(f"event=redis_get_failed error={e}")
        _client = None
        return None


def set_active_products_cache(products):
    global _client
    try:
        _get_client().set(ACTIVE_PRODUCTS_KEY, json.dumps(products), ex=CACHE_TTL_SECONDS)
    except redis.exceptions.RedisError as e:
        logger.warning(f"event=redis_set_failed error={e}")
        _client = None
