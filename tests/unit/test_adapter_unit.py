"""
Adapter unit tests — no infrastructure required (no Gemini, no NiFi).

Tests load PIM fixtures from tests/fixtures/ and run them through
NiFiAdapter, verifying the structure of the output NiFi JSON.

Run:
    pytest tests/unit/test_adapter_unit.py -v
    pytest -m unit -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.nifi_adapter import NiFiAdapter
from src.domain.pim_model import Flow

FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"

pytestmark = pytest.mark.unit


def _load_fixture(name: str) -> Flow:
    path = FIXTURES_DIR / name
    data = json.loads(path.read_text(encoding="utf-8"))
    return Flow.model_validate(data)


def _convert(fixture_name: str) -> dict:
    pim = _load_fixture(fixture_name)
    adapter = NiFiAdapter()
    return adapter.convert(pim)


# ---------------------------------------------------------------------------
# Fixture loading / PIM validation
# ---------------------------------------------------------------------------

class TestFixtureLoading:
    def test_currency_http_to_file_loads(self):
        pim = _load_fixture("currency_http_to_file.json")
        assert pim.flow.id == "currency_http_to_file"
        assert len(pim.sources) == 1
        assert len(pim.sinks) == 1

    def test_kafka_to_postgres_loads(self):
        pim = _load_fixture("kafka_to_postgres.json")
        assert pim.flow.id == "kafka_to_postgres"
        assert pim.sources[0].type == "Kafka"
        assert pim.sinks[0].type == "Database"

    def test_postgres_to_kafka_loads(self):
        pim = _load_fixture("postgres_to_kafka.json")
        assert pim.sources[0].type == "Database"
        assert pim.sinks[0].type == "Kafka"

    def test_s3_to_hdfs_loads(self):
        pim = _load_fixture("s3_to_hdfs.json")
        assert pim.sources[0].type == "S3"
        assert pim.sinks[0].type == "HDFS"


# ---------------------------------------------------------------------------
# Adapter output structure
# ---------------------------------------------------------------------------

class TestAdapterOutputStructure:
    """Verify that NiFiAdapter produces structurally valid NiFi JSON."""

    def _assert_basic_structure(self, result: dict, fixture_name: str):
        assert "flowContents" in result, f"{fixture_name}: missing flowContents"
        fc = result["flowContents"]
        assert "processors" in fc, f"{fixture_name}: missing processors"
        assert "connections" in fc, f"{fixture_name}: missing connections"
        assert len(fc["processors"]) >= 1, f"{fixture_name}: no processors generated"

    def _assert_processors_have_required_fields(self, result: dict):
        for proc in result["flowContents"]["processors"]:
            assert "identifier" in proc, f"Processor missing identifier: {proc.get('name')}"
            assert "type" in proc, f"Processor missing type: {proc.get('name')}"
            assert "bundle" in proc, f"Processor missing bundle: {proc.get('name')}"
            assert "name" in proc, "Processor missing name"

    def _assert_connections_reference_valid_ids(self, result: dict):
        fc = result["flowContents"]
        processor_ids = {p["identifier"] for p in fc["processors"]}
        for conn in fc.get("connections", []):
            src = conn.get("source", {}).get("id")
            dst = conn.get("destination", {}).get("id")
            assert src in processor_ids, f"Connection source {src} not in processors"
            assert dst in processor_ids, f"Connection destination {dst} not in processors"

    def test_currency_http_to_file_structure(self):
        result = _convert("currency_http_to_file.json")
        self._assert_basic_structure(result, "currency_http_to_file")
        self._assert_processors_have_required_fields(result)
        self._assert_connections_reference_valid_ids(result)

    def test_kafka_to_postgres_structure(self):
        result = _convert("kafka_to_postgres.json")
        self._assert_basic_structure(result, "kafka_to_postgres")
        self._assert_processors_have_required_fields(result)
        self._assert_connections_reference_valid_ids(result)

    def test_postgres_to_kafka_structure(self):
        result = _convert("postgres_to_kafka.json")
        self._assert_basic_structure(result, "postgres_to_kafka")
        self._assert_processors_have_required_fields(result)
        self._assert_connections_reference_valid_ids(result)

    def test_s3_to_hdfs_structure(self):
        result = _convert("s3_to_hdfs.json")
        self._assert_basic_structure(result, "s3_to_hdfs")
        self._assert_processors_have_required_fields(result)
        self._assert_connections_reference_valid_ids(result)


# ---------------------------------------------------------------------------
# Processor type presence
# ---------------------------------------------------------------------------

class TestAdapterProcessorTypes:
    """Verify that the adapter picks reasonable processor types for each case."""

    def _get_type_suffixes(self, result: dict) -> set[str]:
        return {
            p["type"].split(".")[-1]
            for p in result["flowContents"]["processors"]
        }

    def test_currency_http_to_file_has_http_and_file(self):
        result = _convert("currency_http_to_file.json")
        suffixes = self._get_type_suffixes(result)
        assert any("InvokeHTTP" in s or "HTTP" in s for s in suffixes), \
            f"Expected HTTP processor, got: {suffixes}"
        assert any("PutFile" in s or "File" in s for s in suffixes), \
            f"Expected File processor, got: {suffixes}"

    def test_kafka_to_postgres_has_kafka_and_db(self):
        result = _convert("kafka_to_postgres.json")
        suffixes = self._get_type_suffixes(result)
        assert any("Kafka" in s for s in suffixes), \
            f"Expected Kafka processor, got: {suffixes}"
        assert any("Database" in s or "Record" in s or "SQL" in s for s in suffixes), \
            f"Expected Database processor, got: {suffixes}"

    def test_postgres_to_kafka_has_db_and_kafka(self):
        result = _convert("postgres_to_kafka.json")
        suffixes = self._get_type_suffixes(result)
        assert any("Database" in s or "Query" in s for s in suffixes), \
            f"Expected Database processor, got: {suffixes}"
        assert any("Kafka" in s for s in suffixes), \
            f"Expected Kafka processor, got: {suffixes}"

    def test_s3_to_hdfs_has_s3_and_hdfs(self):
        result = _convert("s3_to_hdfs.json")
        suffixes = self._get_type_suffixes(result)
        assert any("S3" in s for s in suffixes), \
            f"Expected S3 processor, got: {suffixes}"
        assert any("HDFS" in s for s in suffixes), \
            f"Expected HDFS processor, got: {suffixes}"


class TestAdapterPimPropertyNormalization:
    def test_http_parse_json_file_drops_pim_only_properties(self):
        pim = Flow.model_validate(yaml.safe_load("""
flow:
  id: currency_rates_pipeline
  name: Currency Rates Fetcher
  description: Fetches latest exchange rates from exchangerate.host and saves to rates.json
sources:
- id: source_api
  name: Fetch Exchange Rates
  type: HTTP_API
  location: https://api.exchangerate.host/latest
  connection:
    properties:
      method: GET
processing_elements:
- id: process_format
  name: Format JSON Response
  operation: ParseJSON
  config:
    output_format: json
sinks:
- id: sink_file
  name: Write to File
  type: File
  location: rates.json
  connection:
    properties:
      path: ./rates.json
      write_mode: overwrite
links:
- from_id: source_api
  to_id: process_format
  data_ref: rates_json
- from_id: process_format
  to_id: sink_file
  data_ref: rates_json
"""))

        result = NiFiAdapter().convert(pim)
        processors = result["flowContents"]["processors"]
        suffixes = {p["type"].split(".")[-1] for p in processors}
        assert "ConvertRecord" not in suffixes

        put_file = next(p for p in processors if p["type"].endswith(".PutFile"))
        assert put_file["properties"]["Directory"] == "."
        assert put_file["properties"]["Conflict Resolution Strategy"] == "replace"
        assert "path" not in put_file["properties"]
        assert "write_mode" not in put_file["properties"]

        connections = result["flowContents"]["connections"]
        assert len(connections) == 1
        assert connections[0]["source"]["name"] == "Fetch Exchange Rates"
        assert connections[0]["destination"]["name"] == "Write to File"
