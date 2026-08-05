"""
DB 접근 캡슐화 모듈 (Image Processing Service).

⚠️ products 테이블 상태 변경은 반드시 update_product_status() 하나를 통해서만 이루어져야 한다.
다른 곳에서 products 테이블에 직접 UPDATE 문을 실행하지 않는다 (나중에 이 함수 내부만
이벤트 발행으로 교체하면 서비스 분리가 가능하도록).
"""
import os
import time
import logging

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]

MAX_RETRIES = 10
INITIAL_BACKOFF_SECONDS = 2
MAX_BACKOFF_SECONDS = 60

_conn = None


def _connect_with_retry():
    attempt = 0
    delay = INITIAL_BACKOFF_SECONDS
    while True:
        try:
            conn = psycopg2.connect(DATABASE_URL, connect_timeout=5)
            conn.autocommit = True
            logger.info("event=db_connected")
            return conn
        except psycopg2.OperationalError as e:
            attempt += 1
            if attempt > MAX_RETRIES:
                logger.error(f"event=db_connect_failed attempt={attempt} error={e}")
                raise
            logger.warning(f"event=db_connect_retry attempt={attempt} delay={delay}s error={e}")
            time.sleep(delay)
            delay = min(delay * 2, MAX_BACKOFF_SECONDS)


def init_pool():
    global _conn
    _conn = _connect_with_retry()


def _get_conn():
    global _conn
    if _conn is None or _conn.closed:
        _conn = _connect_with_retry()
    return _conn


def _execute(query, params=None, fetch=None):
    """쿼리 실행 중 연결이 끊긴 경우(예: DB Pod 재기동) 재연결 후 1회 재시도한다."""
    global _conn
    last_error = None
    for attempt in range(2):
        try:
            conn = _get_conn()
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, params)
                if fetch == "one":
                    return cur.fetchone()
                if fetch == "all":
                    return cur.fetchall()
                return None
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            last_error = e
            logger.warning(f"event=db_query_failed_reconnecting attempt={attempt} error={e}")
            _conn = None
            _conn = _connect_with_retry()
    raise last_error


def update_product_status(product_id: int, status: str, reason: str = None):
    """products 테이블 상태 변경을 위한 유일한 진입점.

    나중에 서비스별 DB 분리 시, 이 함수 내부를 이벤트 발행
    ({event: "image_processed", product_id, result, reason})으로 교체하면 된다.
    """
    _execute(
        """
        UPDATE products
        SET status = %s, rejection_reason = %s, updated_at = now()
        WHERE id = %s
        """,
        (status, reason, product_id),
    )
    logger.info(f"event=status_transition product_id={product_id} to={status} reason={reason}")


def insert_product_image(product_id: int, size_type: str, url: str):
    _execute(
        """
        INSERT INTO product_images (product_id, size_type, url)
        VALUES (%s, %s, %s)
        """,
        (product_id, size_type, url),
    )
