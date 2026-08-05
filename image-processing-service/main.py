import logging
import signal

import pika

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

    shutdown_requested = False
    current_channel = None

    def handle_shutdown(signum, frame):
        nonlocal shutdown_requested
        logger.info(f"event=shutdown_signal_received signal={signum}")
        shutdown_requested = True
        # 재연결 대기(백오프) 중이면 channel이 없어 여기서 할 게 없다 — 다음 while 조건 체크에서 빠져나간다.
        if current_channel is not None:
            current_channel.stop_consuming()

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    # RabbitMQ 연결이 실행 중 끊기면(Pod 재배포 등) 프로세스를 죽이지 않고 connect_with_retry()로
    # 재연결 후 컨슘을 재개한다. 정상 종료(SIGTERM/SIGINT)는 run_consumer가 예외 없이 리턴하므로
    # 이 while이 shutdown_requested를 보고 빠져나간다.
    while not shutdown_requested:
        connection, channel = queue_consumer.connect_with_retry()
        current_channel = channel

        logger.info("event=consumer_started")
        try:
            queue_consumer.run_consumer(channel, process_task)
        except (pika.exceptions.AMQPConnectionError, OSError) as e:
            logger.warning(f"event=rabbitmq_connection_lost error={e}")
        finally:
            current_channel = None
            try:
                connection.close()
            except Exception:
                pass

    logger.info("event=consumer_stopped")


if __name__ == "__main__":
    main()
