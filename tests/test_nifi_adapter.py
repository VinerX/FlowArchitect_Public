from __future__ import annotations

from pathlib import Path

from src.adapters.nifi_adapter import NiFiAdapter
from src.domain.pim_model import Flow


def _kafka_to_postgres_flow() -> Flow:
    return Flow.model_validate({
        "flow": {
            "id": "kafka_pg_orders_pipeline",
            "name": "Kafka to PostgreSQL Orders Pipeline",
        },
        "sources": [
            {
                "id": "source_kafka_orders",
                "name": "Read Kafka Orders",
                "type": "Kafka",
                "location": "orders",
                "connection": {
                    "properties": {
                        "brokers": "{{KAFKA_BROKERS}}",
                        "group_id": "orders_consumer_group",
                    },
                },
            },
        ],
        "processing_elements": [
            {
                "id": "process_json_to_table",
                "name": "Parse JSON to Table Rows",
                "operation": "Transform",
                "config": {
                    "input_format": "json",
                    "output_format": "table_rows",
                },
            },
        ],
        "sinks": [
            {
                "id": "sink_postgres_orders",
                "name": "Write to PostgreSQL",
                "type": "PostgreSQL",
                "location": "public.orders",
                "connection": {
                    "properties": {
                        "host": "{{DB_HOST}}",
                        "port": "{{DB_PORT}}",
                        "database": "{{DATABASE_NAME}}",
                        "username": "{{DB_USERNAME}}",
                        "password": "{{DB_PASSWORD}}",
                    },
                },
            },
        ],
        "processed_data": [{"id": "orders_table_data", "format": "table_rows"}],
        "links": [
            {
                "from_id": "source_kafka_orders",
                "to_id": "process_json_to_table",
                "data_ref": "orders_table_data",
            },
            {
                "from_id": "process_json_to_table",
                "to_id": "sink_postgres_orders",
                "data_ref": "orders_table_data",
            },
        ],
    })


def _postgres_to_kafka_flow() -> Flow:
    return Flow.model_validate({
        "flow": {
            "id": "postgres_kafka_pipeline",
            "name": "PostgreSQL to Kafka",
        },
        "sources": [
            {
                "id": "source_postgres",
                "name": "Read PostgreSQL",
                "type": "PostgreSQL",
                "location": "public.products",
                "connection": {
                    "properties": {
                        "host": "localhost",
                        "port": "5432",
                        "database": "postgres",
                        "username": "postgres",
                        "password": "123",
                    },
                },
            },
        ],
        "processing_elements": [],
        "sinks": [
            {
                "id": "sink_kafka",
                "name": "Publish Kafka",
                "type": "Kafka",
                "location": "product-updates",
                "connection": {
                    "properties": {
                        "brokers": "{{KAFKA_BROKERS}}",
                    },
                },
            },
        ],
        "processed_data": [],
        "links": [{"from_id": "source_postgres", "to_id": "sink_kafka"}],
    })


def test_kafka_to_postgres_uses_modern_kafka_stack() -> None:
    result = NiFiAdapter().convert(_kafka_to_postgres_flow())
    processors = result["flowContents"]["processors"]
    processor_types = {proc["type"].split(".")[-1] for proc in processors}

    assert processor_types == {"ConsumeKafka", "PutDatabaseRecord"}

    consume = next(proc for proc in processors if proc["type"].endswith("ConsumeKafka"))
    assert consume["properties"]["Topics"] == "orders"
    assert consume["properties"]["Topic Format"] == "names"
    assert consume["properties"]["Processing Strategy"] == "RECORD"
    assert "Kafka Connection Service" in consume["properties"]
    assert "Kafka Brokers" not in consume["properties"]
    assert "Topic Name(s)" not in consume["properties"]

    services = result["flowContents"]["controllerServices"]
    service_types = {svc["type"].split(".")[-1] for svc in services}
    assert {
        "Kafka3ConnectionService",
        "DBCPConnectionPool",
        "JsonTreeReader",
        "JsonRecordSetWriter",
    }.issubset(service_types)


def test_postgres_to_kafka_uses_modern_publish_kafka() -> None:
    result = NiFiAdapter().convert(_postgres_to_kafka_flow())
    processors = result["flowContents"]["processors"]
    publish = next(proc for proc in processors if proc["name"] == "Publish Kafka")

    assert publish["type"] == "org.apache.nifi.kafka.processors.PublishKafka"
    assert publish["properties"]["Topic Name"] == "product-updates"
    assert "Kafka Connection Service" in publish["properties"]
    assert "Kafka Brokers" not in publish["properties"]


def test_psm_prompt_mentions_modern_kafka_components() -> None:
    prompt = Path("config/prompts/psm_nifi.txt").read_text(encoding="utf-8")

    assert "ConsumeKafka" in prompt
    assert "Kafka3ConnectionService" in prompt
    assert "ConsumeKafka_2_6" not in prompt
