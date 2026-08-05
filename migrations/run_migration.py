"""
DB 마이그레이션 실행 스크립트.

- DATABASE_URL 환경변수로 접속한다.
- 이 디렉토리에 있는 *.sql 파일을 이름 순으로 정렬해 순서대로 실행한다.
- 모든 DDL은 CREATE TABLE IF NOT EXISTS로 작성되어 있으므로 재실행해도 안전하다.
- K8s Job으로 실행될 예정이며, DB Pod가 아직 준비되지 않았을 수 있으므로 접속 실패 시
  크래시하지 않고 지수 백오프로 재시도한다.
"""
import os
import sys
import time
import glob
import logging

import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s level=%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
MIGRATIONS_DIR = os.path.dirname(os.path.abspath(__file__))

MAX_RETRIES = 10
INITIAL_BACKOFF_SECONDS = 2
MAX_BACKOFF_SECONDS = 60


def connect_with_retry():
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


def run_migrations():
    sql_files = sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "*.sql")))
    if not sql_files:
        logger.warning("event=no_migration_files_found dir=%s", MIGRATIONS_DIR)
        return

    conn = connect_with_retry()
    try:
        with conn.cursor() as cur:
            for path in sql_files:
                filename = os.path.basename(path)
                with open(path, "r", encoding="utf-8") as f:
                    sql = f.read()
                logger.info(f"event=migration_started file={filename}")
                cur.execute(sql)
                logger.info(f"event=migration_completed file={filename}")
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        run_migrations()
        logger.info("event=all_migrations_completed")
    except Exception as e:
        logger.error(f"event=migration_failed error={e}")
        sys.exit(1)
