"""
End-to-end integration tests:
  LLM (Gemini) generates PIM JSON → NiFiAdapter converts → NiFiClient imports → verify → cleanup.

Requirements:
  - NiFi running at NIFI_URL (default: https://localhost:8443)
  - Google AI Studio API key (read from config/api_presets.json preset 11, or env GEMINI_API_KEY)

Run all:
  pytest tests/integration/test_e2e_llm_to_nifi.py -v -s

Skip when infrastructure unavailable:
  Tests are auto-skipped if NiFi or the LLM API cannot be reached.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

import pytest
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Project root on sys.path so "from src.xxx" imports work
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.nifi_adapter import NiFiAdapter
from src.domain.pim_model import Flow
from src.services.nifi_client import NiFiClient

# ---------------------------------------------------------------------------
# Config — override with environment variables if needed
# ---------------------------------------------------------------------------

NIFI_URL  = os.getenv("NIFI_URL",  "https://localhost:8443")
NIFI_USER = os.getenv("NIFI_USER", "09ebe0e1-c87a-44f4-9406-20016e700be1")
NIFI_PASS = os.getenv("NIFI_PASS", "eIHP7NIqQmmtH6Kdg0f/r1A1vqfUGNAt")

# Gemini API — reads key from api_presets.json (preset 11) if env var not set
def _load_gemini_key() -> str:
    env_key = os.getenv("GEMINI_API_KEY", "")
    if env_key:
        return env_key
    try:
        presets_path = PROJECT_ROOT / "config" / "api_presets.json"
        data = json.loads(presets_path.read_text(encoding="utf-8"))
        return data["presets"]["11"]["key"]
    except Exception:
        return ""

GEMINI_API_KEY = _load_gemini_key()
# gemini-2.0-flash is faster and more stable for batch test runs;
# override with GEMINI_MODEL env var to test with a different model
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_URL     = (
    f"https://generativelanguage.googleapis.com/v1beta/models"
    f"/{GEMINI_MODEL}:generateContent"
)
PROMPT_FILE = PROJECT_ROOT / "config" / "prompts" / "system_architect.txt"


# ---------------------------------------------------------------------------
# Infrastructure availability checks (evaluated once at collection time)
# ---------------------------------------------------------------------------

def _nifi_available() -> bool:
    try:
        client = NiFiClient(NIFI_URL, NIFI_USER, NIFI_PASS, timeout=5)
        ok, _ = client.test_connection()
        return ok
    except Exception:
        return False


def _llm_available() -> bool:
    if not GEMINI_API_KEY:
        return False
    try:
        r = requests.get(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}",
            timeout=10,
        )
        return r.status_code == 200
    except Exception:
        return False


_NIFI_UP = _nifi_available()
_LLM_UP  = _llm_available()

pytestmark = pytest.mark.integration

requires_nifi = pytest.mark.skipif(not _NIFI_UP, reason="NiFi not reachable")
requires_llm  = pytest.mark.skipif(not _LLM_UP,  reason="Gemini API not available")


# ---------------------------------------------------------------------------
# LLM helper
# ---------------------------------------------------------------------------

def _call_gemini(query: str, retries: int = 2) -> str:
    """
    Build the system_architect prompt, call Gemini generateContent,
    and return the raw JSON string from the model response.

    Uses responseMimeType=application/json so Gemini returns pure JSON
    without markdown fences (structured output).
    Retries *retries* times on transient network errors.
    """
    prompt_template = PROMPT_FILE.read_text(encoding="utf-8")
    # Safe substitution: replace {query} literally, ignore other braces
    full_prompt = prompt_template.replace("{query}", query)

    body = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": full_prompt}],
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
        },
    }

    import time as _time
    last_exc: Optional[Exception] = None
    for attempt in range(1 + retries):
        try:
            r = requests.post(
                f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                json=body,
                timeout=150,
            )
            if r.status_code == 429 and attempt < retries:
                # Honour Retry-After; default 65 s (covers 1-minute quota window)
                wait = int(r.headers.get("Retry-After", 65))
                print(f"[LLM] 429 rate-limited, waiting {wait}s before retry...")
                _time.sleep(wait)
                continue
            r.raise_for_status()
            candidates = r.json().get("candidates", [])
            assert candidates, f"Gemini returned no candidates: {r.text[:400]}"
            return candidates[0]["content"]["parts"][0]["text"]
        except requests.exceptions.ReadTimeout as exc:
            last_exc = exc
            if attempt < retries:
                print(f"[LLM] attempt {attempt + 1} timed out, retrying...")
                _time.sleep(5)
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                print(f"[LLM] attempt {attempt + 1} failed ({exc}), retrying...")
                _time.sleep(5)
    raise RuntimeError(f"Gemini API failed after {1 + retries} attempts") from last_exc


# ---------------------------------------------------------------------------
# PIM parsing helper (mirrors Orchestrator._parse_json_to_flow)
# ---------------------------------------------------------------------------

def _parse_pim(json_text: str) -> Flow:
    """Parse LLM output (JSON string, possibly in markdown fences) into PIMFlow."""
    raw = json_text.strip()
    # Strip markdown fences if present despite responseMimeType
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    if m:
        raw = m.group(1).strip()
    data = json.loads(raw)
    return Flow.model_validate(data)


# ---------------------------------------------------------------------------
# NiFi cleanup fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def nifi_client_fixture() -> NiFiClient:
    return NiFiClient(NIFI_URL, NIFI_USER, NIFI_PASS)


@pytest.fixture
def nifi_pg_cleanup(nifi_client_fixture):
    """Collect created process-group IDs and delete them after the test."""
    created: list[str] = []
    yield created
    for pg_id in created:
        try:
            nifi_client_fixture.delete_pg(pg_id)
            print(f"[cleanup] deleted PG {pg_id}")
        except Exception as e:
            print(f"[cleanup] WARNING: could not delete PG {pg_id}: {e}")


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

E2E_CASES = [
    pytest.param(
        "Получай курс валют с сайта https://api.exchangerate.host/latest "
        "и записывай результат в файл rates.json",
        # Expected NiFi processor class-name suffixes (substring match)
        ["InvokeHTTP", "PutFile"],
        id="currency-http-to-file",
    ),
    pytest.param(
        "Читай сообщения из Kafka-топика 'orders' и сохраняй их в PostgreSQL "
        "в таблицу orders_archive",
        ["ConsumeKafka", "PutDatabaseRecord"],
        id="kafka-to-postgres",
    ),
    pytest.param(
        "Каждые 5 минут читай таблицу products из PostgreSQL и отправляй "
        "изменения в Kafka-топик product-updates",
        ["QueryDatabaseTable", "PublishKafka"],
        id="postgres-to-kafka",
    ),
    pytest.param(
        "Скачивай файлы из S3 бакета raw-data и сохраняй их в HDFS",
        # Adapter may use ListS3 or FetchS3Object depending on query phrasing
        ["S3", "HDFS"],
        id="s3-to-hdfs",
    ),
]


@pytest.mark.parametrize("query, expected_suffixes", E2E_CASES)
@requires_nifi
@requires_llm
def test_e2e_llm_to_nifi(query: str, expected_suffixes: list[str], nifi_pg_cleanup):
    """
    Full pipeline:
      1. LLM generates structured PIM JSON from natural-language query
      2. JSON validated and parsed into PIMFlow
      3. NiFiAdapter converts PIMFlow → NiFi flow JSON
      4. NiFiClient imports the flow into live NiFi
      5. Assert correct processors are present in NiFi
      6. Cleanup (via fixture)
    """
    # ── Step 1: LLM generation ──────────────────────────────────────────────
    import time
    time.sleep(2)  # brief pause to stay within API rate limits between test cases
    print(f"\n[query] {query}")
    raw_json = _call_gemini(query)
    print(f"[LLM raw] {raw_json[:400]}{'...' if len(raw_json) > 400 else ''}")

    # ── Step 2: Parse JSON → PIMFlow ────────────────────────────────────────
    pim = _parse_pim(raw_json)
    assert pim.flow.id,   "PIM must have a non-empty flow.id"
    assert pim.flow.name, "PIM must have a non-empty flow.name"
    assert pim.sources or pim.sinks, "PIM must have at least one source or sink"
    print(f"[PIM] flow='{pim.flow.name}', "
          f"sources={len(pim.sources)}, "
          f"processing={len(pim.processing_elements)}, "
          f"sinks={len(pim.sinks)}")

    # ── Step 3: PIMFlow → NiFi JSON ─────────────────────────────────────────
    adapter = NiFiAdapter()
    nifi_json = adapter.convert(pim)
    processors = nifi_json["flowContents"]["processors"]
    assert processors, "Adapter must produce at least one processor"

    proc_types = {p["type"] for p in processors}
    proc_suffixes = {t.split(".")[-1] for t in proc_types}
    print(f"[adapter] {len(processors)} processor(s): {proc_suffixes}")

    for expected in expected_suffixes:
        matched = any(expected.lower() in s.lower() for s in proc_suffixes)
        assert matched, (
            f"Expected processor matching '{expected}' not found.\n"
            f"Got: {proc_suffixes}\n"
            f"LLM output was:\n{raw_json}"
        )

    # ── Step 4: Import to NiFi ──────────────────────────────────────────────
    client = NiFiClient(NIFI_URL, NIFI_USER, NIFI_PASS)
    ok, result = client.import_flow(nifi_json)
    assert ok, f"NiFi import failed: {result}"
    nifi_pg_cleanup.append(result)
    print(f"[NiFi] process-group created: {result}")

    # ── Step 5: Verify processors are accessible in NiFi ────────────────────
    token = client._get_token()
    r = requests.get(
        f"{NIFI_URL}/nifi-api/process-groups/{result}/processors",
        headers={"Authorization": f"Bearer {token}"},
        verify=False,
        timeout=10,
    )
    r.raise_for_status()
    nifi_procs = r.json().get("processors", [])

    assert len(nifi_procs) >= 1, (
        f"No processors found in NiFi PG {result} after import"
    )

    # Verify that every expected suffix appears somewhere in the imported types
    nifi_types = {
        p["component"]["type"].split(".")[-1]
        for p in nifi_procs
    }
    print(f"[NiFi] {len(nifi_procs)} processor(s) found: {nifi_types}")
    for expected in expected_suffixes:
        assert any(expected.lower() in t.lower() for t in nifi_types), (
            f"Expected processor matching '{expected}' not found in NiFi.\n"
            f"NiFi has: {nifi_types}"
        )


# ---------------------------------------------------------------------------
# Unit-style sub-tests (no infrastructure required)
# ---------------------------------------------------------------------------

class TestLlmOutputParsing:
    """Verify that _parse_pim handles all realistic LLM output shapes."""

    _VALID_PIM = {
        "flow": {"id": "test_flow", "name": "Test"},
        "triggers": [{"id": "t1", "type": "schedule", "condition": "every hour"}],
        "sources": [{"id": "s1", "name": "HTTP", "type": "HTTP",
                     "location": "https://api.example.com/data"}],
        "processing_elements": [],
        "sinks": [{"id": "k1", "name": "File", "type": "File", "location": "out.json"}],
        "processed_data": [],
        "links": [{"from_id": "s1", "to_id": "k1"}],
    }

    def test_plain_json(self):
        raw = json.dumps(self._VALID_PIM)
        pim = _parse_pim(raw)
        assert pim.flow.id == "test_flow"

    def test_json_in_markdown_fence(self):
        raw = "```json\n" + json.dumps(self._VALID_PIM) + "\n```"
        pim = _parse_pim(raw)
        assert pim.flow.id == "test_flow"

    def test_manual_trigger_accepted(self):
        data = dict(self._VALID_PIM)
        data["triggers"] = [{"id": "t1", "type": "manual", "condition": "on demand"}]
        pim = _parse_pim(json.dumps(data))
        assert pim.triggers[0].type == "manual"

    def test_invalid_trigger_type_raises(self):
        data = dict(self._VALID_PIM)
        data["triggers"] = [{"id": "t1", "type": "on_demand", "condition": "x"}]
        with pytest.raises((ValueError, Exception)):
            _parse_pim(json.dumps(data))

    def test_missing_required_fields_raises(self):
        with pytest.raises((ValueError, Exception)):
            _parse_pim('{"triggers": []}')  # missing "flow"


class TestPromptSubstitution:
    """Verify that the prompt template substitution works with JSON content."""

    def test_query_replaced(self):
        template = 'Describe {query} in JSON: {"key": "value"}'
        result = template.replace("{query}", "test query")
        assert "test query" in result
        assert '{"key": "value"}' in result  # JSON braces must be untouched

    def test_prompt_file_loads(self):
        assert PROMPT_FILE.exists(), f"Prompt file not found: {PROMPT_FILE}"
        text = PROMPT_FILE.read_text(encoding="utf-8")
        assert "{query}" in text, "Prompt must contain {query} placeholder"

    def test_prompt_file_substitution(self):
        text = PROMPT_FILE.read_text(encoding="utf-8")
        result = text.replace("{query}", "retrieve exchange rates and save to file")
        assert "{query}" not in result
        # The JSON schema in the prompt should be intact
        assert '"flow"' in result
