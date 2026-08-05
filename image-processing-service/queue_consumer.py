"""
RabbitMQ 소비 모듈 (Image Processing Service).

manual ack 모드로 동작하며, 처리 실패 시 메시지 헤더(x-retry-count)에 재시도 횟수를 기록해
같은 큐로 재발행한다. 최대 3회(MAX_PROCESS_RETRIES) 재시도 후에도 실패하면 DLQ로 이동시킨다.
"""
import os
import json
import time
import logging
from pathlib import Path

import pika

logger = logging.getLogger(__name__)

RABBITMQ_URL = os.environ["RABBITMQ_URL"]
QUEUE_NAME = "image_processing"
DLQ_NAME = "image_processing.dlq"
MAX_PROCESS_RETRIES = 3

MAX_CONNECT_RETRIES = 10
INITIAL_BACKOFF_SECONDS = 2
MAX_BACKOFF_SECONDS = 60

# K8s liveness/readiness probe(exec)가 이 파일의 mtime 신선도로 RabbitMQ 연결 상태를 판단한다.
# 연결 성공 직후, 그리고 컨슘 루프가 살아있는 동안 주기적으로 touch되며, 재연결 시도 중에는
# 갱신되지 않아야 하므로 connect_with_retry() 실패 경로에서는 절대 touch하지 않는다.
HEALTH_FILE = Path(os.environ.get("RABBITMQ_HEALTH_FILE", "/tmp/healthy"))
HEARTBEAT_INTERVAL_SECONDS = 30


def _touch_health_file():
    HEALTH_FILE.touch()


def connect_with_retry():
    attempt = 0
    delay = INITIAL_BACKOFF_SECONDS
    while True:
        try:
            params = pika.URLParameters(RABBITMQ_URL)
            connection = pika.BlockingConnection(params)
            channel = connection.channel()
            channel.queue_declare(queue=QUEUE_NAME, durable=True)
            channel.queue_declare(queue=DLQ_NAME, durable=True)
            channel.basic_qos(prefetch_count=1)
            logger.info("event=rabbitmq_connected")
            _touch_health_file()
            return connection, channel
        except (pika.exceptions.AMQPConnectionError, OSError) as e:
            attempt += 1
            if attempt > MAX_CONNECT_RETRIES:
                logger.error(f"event=rabbitmq_connect_failed attempt={attempt} error={e}")
                raise
            logger.warning(f"event=rabbitmq_connect_retry attempt={attempt} delay={delay}s error={e}")
            time.sleep(delay)
            delay = min(delay * 2, MAX_BACKOFF_SECONDS)


def run_consumer(channel, process_fn):
    """process_fn(product_id, temp_image_key)를 호출한다. 실패 시 예외를 던져야 재시도가 동작한다."""

    def _on_message(ch, method, properties, body):
        payload = json.loads(body)
        product_id = payload["product_id"]
        temp_image_key = payload["temp_image_key"]
        retry_count = (properties.headers or {}).get("x-retry-count", 0)

        try:
            process_fn(product_id, temp_image_key)
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except Exception as e:
            next_retry_count = retry_count + 1
            logger.error(f"event=processing_failed product_id={product_id} retry_count={retry_count} error={e}")

            if next_retry_count > MAX_PROCESS_RETRIES:
                logger.error(f"event=moved_to_dlq product_id={product_id} retry_count={next_retry_count}")
                ch.basic_publish(
                    exchange="",
                    routing_key=DLQ_NAME,
                    body=body,
                    properties=pika.BasicProperties(delivery_mode=2, headers={"x-retry-count": next_retry_count}),
                )
            else:
                logger.warning(f"event=requeued_for_retry product_id={product_id} next_retry_count={next_retry_count}")
                ch.basic_publish(
                    exchange="",
                    routing_key=QUEUE_NAME,
                    body=body,
                    properties=pika.BasicProperties(delivery_mode=2, headers={"x-retry-count": next_retry_count}),
                )

            ch.basic_ack(delivery_tag=method.delivery_tag)

        _touch_health_file()

    def _heartbeat():
        _touch_health_file()
        channel.connection.call_later(HEARTBEAT_INTERVAL_SECONDS, _heartbeat)

    channel.connection.call_later(HEARTBEAT_INTERVAL_SECONDS, _heartbeat)
    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=_on_message)
    channel.start_consuming()
