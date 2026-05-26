import json
from typing import Callable

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


async def get_producer() -> AIOKafkaProducer:
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
    )
    await producer.start()
    return producer


async def send_task(producer: AIOKafkaProducer, task_data: dict) -> None:
    await producer.send(settings.kafka_topic_emails, value=task_data)
    task_id = task_data.get("task_id", "unknown")
    logger.info("kafka.task_sent", task_id=task_id, topic=settings.kafka_topic_emails)


async def start_consumer(handler: Callable) -> None:
    consumer = AIOKafkaConsumer(
        settings.kafka_topic_emails,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=True,
    )
    await consumer.start()
    logger.info("kafka.consumer_started", topic=settings.kafka_topic_emails)

    try:
        async for msg in consumer:
            logger.info(
                "kafka.message_received",
                task_id=msg.value.get("task_id"),
                partition=msg.partition,
                offset=msg.offset,
            )
            try:
                await handler(msg.value)
            except Exception as exc:
                logger.error(
                    "kafka.handler_failed",
                    task_id=msg.value.get("task_id"),
                    error=str(exc),
                    exc_info=True,
                )
    finally:
        await consumer.stop()
