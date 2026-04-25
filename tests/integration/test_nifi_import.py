"""
Integration tests: generate NiFi flow JSON via NiFiAdapter → import into live NiFi → cleanup.

Requirements:
  - NiFi must be running (default: http://localhost:8443)
  - Set env vars if needed:
      NIFI_URL   — base URL without trailing slash  (default: https://localhost:8443)
      NIFI_USER  — username                         (default: admin)
      NIFI_PASS  — password                         (default: adminadminadmin)

Run:
  pytest tests/integration/test_nifi_import.py -v
  pytest tests/integration/test_nifi_import.py -v --nifi-url http://localhost:8080

Skip when NiFi is unavailable:
  pytest tests/integration/test_nifi_import.py -v -m nifi_import
  (tests are auto-skipped if NiFi is unreachable)
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
from typing import Generator

import pytest
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Add project root to sys.path so imports match those inside the adapter
# (adapter uses "from src.domain..." which requires project root, not src/)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from src.adapters.nifi_adapter import NiFiAdapter
from src.domain.pim_model import (
    ConnectionConfig,
    DataFlow,
    DataProcessingElement,
    DataSink,
    DataSource,
    Link,
    PIMFlow,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NIFI_URL  = os.getenv("NIFI_URL",  "https://localhost:8443")
NIFI_USER = os.getenv("NIFI_USER", "09ebe0e1-c87a-44f4-9406-20016e700be1")
NIFI_PASS = os.getenv("NIFI_PASS", "eIHP7NIqQmmtH6Kdg0f/r1A1vqfUGNAt")


def _get_token() -> str:
    """Obtain a JWT bearer token from NiFi (single-user auth, NiFi 2.x)."""
    r = requests.post(
        f"{NIFI_URL}/nifi-api/access/token",
        data={"username": NIFI_USER, "password": NIFI_PASS},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        verify=False,
        timeout=10,
    )
    r.raise_for_status()
    return r.text.strip()


SESSION = requests.Session()
SESSION.verify = False
SESSION.headers.update({"Content-Type": "application/json"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _api(path: str) -> str:
    return f"{NIFI_URL}/nifi-api{path}"


def _nifi_available() -> bool:
    try:
        token = _get_token()
        r = SESSION.get(
            _api("/flow/about"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        return r.status_code < 500
    except Exception:
        return False


def _root_pg_id() -> str:
    token = _get_token()
    r = SESSION.get(
        _api("/flow/process-groups/root"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["processGroupFlow"]["id"]


def _import_flow(parent_pg_id: str, flow_json: dict) -> str:
    """
    Create a new process group inside *parent_pg_id* populated with *flow_json*.
    Returns the new process-group id.
    """
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    flow_contents = flow_json["flowContents"]
    name = flow_contents.get("name", "test-flow")

    body = {
        "revision": {"version": 0},
        "component": {
            "name": name,
            "position": {"x": 0.0, "y": 0.0},
        },
        "versionedFlowSnapshot": {
            "flowContents": flow_contents,
            "externalControllerServices": {},
            "parameterContexts": {},
            "flowEncodingVersion": "1.0",
        },
    }

    r = SESSION.post(
        _api(f"/process-groups/{parent_pg_id}/process-groups"),
        data=json.dumps(body),
        headers=headers,
        timeout=30,
    )
    assert r.status_code == 201, (
        f"Import failed [{r.status_code}]:\n{r.text[:800]}"
    )
    return r.json()["id"]


def _delete_pg(pg_id: str) -> None:
    """Stop all processors, then delete the process group."""
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    SESSION.put(
        _api(f"/flow/process-groups/{pg_id}"),
        data=json.dumps({"id": pg_id, "state": "STOPPED"}),
        headers=headers,
        timeout=10,
    )
    r = SESSION.get(_api(f"/process-groups/{pg_id}"), headers=headers, timeout=10)
    if r.status_code == 404:
        return
    version = r.json()["revision"]["version"]
    SESSION.delete(
        _api(f"/process-groups/{pg_id}"),
        params={"version": version},
        headers=headers,
        timeout=10,
    )


# ---------------------------------------------------------------------------
# Pytest fixtures / marks
# ---------------------------------------------------------------------------

pytestmark = [pytest.mark.integration, pytest.mark.nifi_import]


def pytest_addoption(parser):
    parser.addoption("--nifi-url", default=None, help="NiFi base URL")


@pytest.fixture(scope="session", autouse=True)
def nifi_check():
    if not _nifi_available():
        pytest.skip("NiFi is not reachable — skipping all nifi_import tests")


@pytest.fixture(scope="session")
def root_pg_id() -> str:
    return _root_pg_id()


@pytest.fixture
def imported_pg(root_pg_id) -> Generator[str, None, None]:
    """Yields pg_id of imported flow, deletes it after the test."""
    created: list[str] = []

    def do_import(flow_json: dict) -> str:
        pg_id = _import_flow(root_pg_id, flow_json)
        created.append(pg_id)
        return pg_id

    yield do_import

    for pg_id in created:
        _delete_pg(pg_id)


# ---------------------------------------------------------------------------
# PIM builders
# ---------------------------------------------------------------------------

def _make_pim_file_to_file() -> PIMFlow:
    """Minimal: File source → File sink (no controller services needed)."""
    return PIMFlow(
        flow=DataFlow(id="test_file_to_file", name="Test File to File"),
        sources=[DataSource(id="src", name="File Source", type="File", location="/input")],
        sinks=[DataSink(id="snk", name="File Sink", type="File", location="/output")],
        links=[Link(from_id="src", to_id="snk")],
    )


def _make_pim_db_to_file() -> PIMFlow:
    """PostgreSQL source → File sink (needs DBCPConnectionPool)."""
    return PIMFlow(
        flow=DataFlow(id="test_db_to_file", name="Test DB to File"),
        sources=[
            DataSource(
                id="src_db",
                name="PostgreSQL Source",
                type="PostgreSQL",
                location="public.orders",
                connection=ConnectionConfig(properties={
                    "host": "db-host", "port": "5432", "database": "analytics",
                }),
            )
        ],
        sinks=[DataSink(id="snk_file", name="File Sink", type="File", location="/output")],
        links=[Link(from_id="src_db", to_id="snk_file")],
    )


def _make_pim_kafka_transform_db() -> PIMFlow:
    """Kafka → Filter → PostgreSQL (needs DBCPConnectionPool + record services)."""
    return PIMFlow(
        flow=DataFlow(id="test_kafka_db", name="Test Kafka Transform DB"),
        sources=[
            DataSource(
                id="src_kafka",
                name="Kafka Source",
                type="Kafka",
                location="orders",
                connection=ConnectionConfig(properties={"brokers": "kafka:9092"}),
            )
        ],
        processing_elements=[
            DataProcessingElement(
                id="proc_filter",
                name="Filter Orders",
                operation="Filter",
                config={"condition": "amount > 100"},
            )
        ],
        sinks=[
            DataSink(
                id="snk_db",
                name="PostgreSQL Sink",
                type="PostgreSQL",
                location="public.high_value_orders",
            )
        ],
        links=[
            Link(from_id="src_kafka",  to_id="proc_filter"),
            Link(from_id="proc_filter", to_id="snk_db"),
        ],
    )


def _make_pim_http_to_s3() -> PIMFlow:
    """HTTP source → S3 sink (tests AWS adapter path)."""
    return PIMFlow(
        flow=DataFlow(id="test_http_s3", name="Test HTTP to S3"),
        sources=[DataSource(id="src_http", name="HTTP Source", type="HTTP", location="http://api/data")],
        sinks=[DataSink(id="snk_s3", name="S3 Sink", type="S3", location="s3://my-bucket/out/")],
        links=[Link(from_id="src_http", to_id="snk_s3")],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

ADAPTER = NiFiAdapter()


@pytest.mark.parametrize("pim,label", [
    (_make_pim_file_to_file(),         "file→file"),
    (_make_pim_db_to_file(),           "db→file (DBCP)"),
    (_make_pim_kafka_transform_db(),   "kafka→filter→db (DBCP+record-services)"),
    (_make_pim_http_to_s3(),           "http→s3"),
])
def test_nifi_import_succeeds(pim, label, imported_pg):
    """NiFi must accept the generated flow JSON without 5xx errors."""
    flow_json = ADAPTER.convert(pim)

    # Sanity-check generated JSON before sending
    assert "flowContents" in flow_json, "Adapter did not produce flowContents"
    for proc in flow_json["flowContents"]["processors"]:
        assert "bundle" in proc,               f"Processor {proc['name']} missing bundle"
        assert "propertyDescriptors" in proc,  f"Processor {proc['name']} missing propertyDescriptors"
    for conn in flow_json["flowContents"]["connections"]:
        assert "labelIndex" in conn,           f"Connection {conn.get('name')} missing labelIndex"
    for svc in flow_json["flowContents"]["controllerServices"]:
        assert "bundle" in svc,               f"Service {svc['name']} missing bundle"
        assert "propertyDescriptors" in svc,  f"Service {svc['name']} missing propertyDescriptors"

    # Import into NiFi — fixture auto-cleans up
    pg_id = imported_pg(flow_json)
    assert pg_id, f"[{label}] Import returned empty pg_id"


def test_nifi_import_json_is_valid_json(tmp_path):
    """Adapter output must be serialisable to JSON (no datetime, UUID objects, etc.)."""
    pim = _make_pim_db_to_file()
    flow_json = ADAPTER.convert(pim)
    raw = json.dumps(flow_json)          # raises if not serialisable
    parsed = json.loads(raw)
    assert parsed["flowContents"]["processors"]
