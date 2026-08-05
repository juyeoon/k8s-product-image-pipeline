"""
DB 접근 캡슐화 모듈 (Product Service).

테이블 소유권은 models.py 상단 주석 참고.
Product Service는 products 테이블만 쓰기(INSERT)하며, product_images 테이블은
상세/목록 조회 시 읽기(SELECT)만 수행한다 (⚠️ 쓰기 금지).
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
    """서비스 기동 시 최초 연결을 확립한다. DB가 아직 준비되지 않았어도 크래시하지 않고 재시도한다."""
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


def health_check() -> bool:
    """K8s Liveness/Readiness Probe용 - 재시도/백오프 없이 짧은 타임아웃으로 1회만 확인한다.

    _execute()가 사용하는 재연결 로직은 최대 10회, 백오프 최대 60초까지 기다리므로
    Probe 응답에는 부적합하다. 여기서는 DB 장애를 빠르게 감지해 503을 반환하는 것이 목적이다.
    """
    try:
        with psycopg2.connect(DATABASE_URL, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return True
    except psycopg2.OperationalError as e:
        logger.error(f"event=db_health_check_failed error={e}")
        return False


def insert_draft_product(name: str, price: int, description: str) -> int:
    row = _execute(
        """
        INSERT INTO products (name, price, description, status)
        VALUES (%s, %s, %s, 'draft')
        RETURNING id
        """,
        (name, price, description),
        fetch="one",
    )
    return row["id"]


def get_product(product_id: int):
    product = _execute(
        """
        SELECT id, name, price, description, status, rejection_reason, created_at, updated_at
        FROM products
        WHERE id = %s
        """,
        (product_id,),
        fetch="one",
    )
    if product is None:
        return None

    # product_images는 Image Processing Service 소유 테이블 - 읽기 전용 조회만 수행
    images = _execute(
        "SELECT size_type, url FROM product_images WHERE product_id = %s ORDER BY size_type",
        (product_id,),
        fetch="all",
    )

    result = dict(product)
    result["images"] = [dict(row) for row in images]
    return result


def list_active_products():
    rows = _execute(
        """
        SELECT p.id, p.name, p.price, p.description,
               (SELECT pi.url FROM product_images pi
                WHERE pi.product_id = p.id AND pi.size_type = 'thumbnail'
                LIMIT 1) AS thumbnail_url
        FROM products p
        WHERE p.status = 'active'
        ORDER BY p.created_at DESC
        """,
        fetch="all",
    )
    return [dict(row) for row in rows]


def list_all_products():
    """상태와 무관하게 모든 상품을 최신순으로 반환한다 (발표용 Web UI 판매자 화면 전용)."""
    rows = _execute(
        """
        SELECT id, name, price, status, rejection_reason
        FROM products
        ORDER BY created_at DESC
        """,
        fetch="all",
    )
    return [dict(row) for row in rows]
