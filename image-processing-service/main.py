import logging
import signal

import db
import storage
import processor
import queue_consumer

logging.basicConfig(level=logging.INFO, format="%(asctime)s level=%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def process_task(product_id: int, temp_image_key: str):
    db.update_product_status(product_id, "processing")

    file_bytes = storage.download_temp_image(temp_image_key)
    passed, reason, image = processor.inspect_image(file_bytes)

    if passed:
        sizes = processor.resize_and_upload(product_id, image)
        for size_type, url in sizes:
            db.insert_product_image(product_id, size_type, url)
        db.update_product_status(product_id, "active")
    else:
        db.update_product_status(product_id, "rejected", reason=reason)

    # DLQ로 넘어간 경우를 제외하면(재시도 중에는 이 함수가 예외로 종료되어 아래 줄에 도달하지 않음)
    # 성공/반려 무관하게 temp/ 원본은 처리 완료 즉시 삭제한다.
    storage.delete_temp_image(temp_image_key)


def main():
    db.init_pool()
    connection, channel = queue_consumer.connect_with_retry()

    def handle_shutdown(signum, frame):
        logger.info(f"event=shutdown_signal_received signal={signum}")
        channel.stop_consuming()

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    logger.info("event=consumer_started")
    try:
        queue_consumer.run_consumer(channel, process_task)
    finally:
        connection.close()
        logger.info("event=consumer_stopped")


if __name__ == "__main__":
    main()
