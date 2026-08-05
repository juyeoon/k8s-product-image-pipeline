"""RabbitMQ 발행 모듈 (Product Service). 이미지 처리 작업 메시지를 발행한다."""
import os
import json
import time
import logging

import pika

logger = logging.getLogger(__name__)

RABBITMQ_URL = os.environ["RABBITMQ_URL"]
QUEUE_NAME = "image_processing"

MAX_RETRIES = 10
INITIAL_BACKOFF_SECONDS = 2
MAX_BACKOFF_SECONDS = 60

_connection = None
_channel = None


def _connect_with_retry():
    attempt = 0
    delay = INITIAL_BACKOFF_SECONDS
    while True:
        try:
            params = pika.URLParameters(RABBITMQ_URL)
            connection = pika.BlockingConnection(params)
            channel = connection.channel()
            channel.queue_declare(queue=QUEUE_NAME, durable=True)
            logger.info("event=rabbitmq_connected")
            return connection, channel
        except (pika.exceptions.AMQPConnectionError, OSError) as e:
            attempt += 1
            if attempt > MAX_RETRIES:
                logger.error(f"event=rabbitmq_connect_failed attempt={attempt} error={e}")
                raise
            logger.warning(f"event=rabbitmq_connect_retry attempt={attempt} delay={delay}s error={e}")
            time.sleep(delay)
            delay = min(delay * 2, MAX_BACKOFF_SECONDS)


def init_connection():
    global _connection, _channel
    _connection, _channel = _connect_with_retry()


def publish_image_processing_task(product_id: int, temp_image_key: str):
    global _connection, _channel
    message = json.dumps({"product_id": product_id, "temp_image_key": temp_image_key})

    for attempt in range(2):
        try:
            if _channel is None or _channel.is_closed:
                _connection, _channel = _connect_with_retry()
            _channel.basic_publish(
                exchange="",
                routing_key=QUEUE_NAME,
                body=message,
                properties=pika.BasicProperties(delivery_mode=2),
            )
            logger.info(f"event=task_published product_id={product_id} temp_image_key={temp_image_key}")
            return
        except (pika.exceptions.AMQPError, OSError) as e:
            logger.warning(f"event=publish_failed_reconnecting attempt={attempt} error={e}")
            _connection, _channel = _connect_with_retry()

    raise RuntimeError(f"failed to publish message for product_id={product_id} after retry")
