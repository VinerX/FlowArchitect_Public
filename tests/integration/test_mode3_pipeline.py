"""
Integration tests for Mode 3: Adapter + LLM semantic corrector.

Mode 3 pipeline:
  PIM YAML → NiFiAdapter → adapter JSON → LLM (nifi_corrector prompt) → corrected JSON

Requirements:
  - Google AI Studio API key (read from config/api_presets.json preset 11, or env GEMINI_API_KEY)
  - No NiFi required (tests only verify the corrector output, not import)

Run:
    pytest tests/integration/test_mode3_pipeline.py -v -s
    pytest -m integration -v
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

import pytest
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.nifi_adapter import NiFiAdapter
from src.domain.pim_model import Flow

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
CORRECTOR_PROMPT_FILE = PROJECT_ROOT / "config" / "prompts" / "nifi_corrector.txt"
HF_YAML = PROJECT_ROOT / "tests" / "HaggingFace.yaml"


def _load_gemini_key() -> str:
    env_key = os.getenv("GEMINI_API_KEY", "")
    if env_key:
        return env_key
    try:
        data = json.loads((PROJECT_ROOT / "config" / "api_presets.json").read_text(encoding="utf-8"))
        return data["presets"]["11"]["key"]
    except Exception:
        return ""


GEMINI_API_KEY = _load_gemini_key()

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Infrastructure availability
# ---------------------------------------------------------------------------

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


_LLM_UP = _llm_available()
requires_llm = pytest.mark.skipif(not _LLM_UP, reason="Gemini API not available")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_pim_yaml(path: Path) -> tuple[Flow, str]:
    import yaml
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    return Flow.model_validate(data), text


def _build_corrector_prompt(pim_yaml: str, nifi_json: str) -> str:
    template = CORRECTOR_PROMPT_FILE.read_text(encoding="utf-8")
    return template.replace("{pim_yaml}", pim_yaml).replace("{nifi_json}", nifi_json)


def _call_gemini_corrector(prompt: str, retries: int = 2) -> str:
    """Call Gemini with the nifi_corrector prompt; return raw response text."""
    body = {
        "system_instruction": {"parts": [{"text": prompt}]},
        "contents": [{"role": "user", "parts": [
            {"text": "Fix semantic errors and return the corrected NiFi JSON."}
        ]}],
        "generationConfig": {"temperature": 0.1},
    }
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models"
        f"/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )

    last_exc: Optional[Exception] = None
    for attempt in range(1 + retries):
        try:
            r = requests.post(url, json=body, timeout=120)
            if r.status_code == 429 and attempt < retries:
                wait = int(r.headers.get("Retry-After", 65))
                print(f"[LLM] 429 rate-limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            candidates = r.json().get("candidates", [])
            assert candidates, f"Gemini returned no candidates: {r.text[:400]}"
            parts = candidates[0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts)
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                print(f"[LLM] attempt {attempt + 1} failed ({exc}), retrying...")
                time.sleep(5)
    raise RuntimeError(f"Gemini API failed after {1 + retries} attempts") from last_exc


def _extract_json(text: str) -> dict:
    """Extract JSON dict from LLM response (handles ```json fences)."""
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    raw = m.group(1).strip() if m else text.strip()
    return json.loads(raw)


def _get_processor_by_type(result: dict, type_suffix: str) -> Optional[dict]:
    for p in result.get("flowContents", {}).get("processors", []):
        if p.get("type", "").endswith(type_suffix):
            return p
    return None


# ---------------------------------------------------------------------------
# Unit-style tests (no LLM — verify adapter output before correction)
# ---------------------------------------------------------------------------

class TestAdapterOutputBeforeCorrection:
    """Verify the adapter produces the known semantic issues in HaggingFace.yaml."""

    def test_query_record_has_non_calcite_sql(self):
        pim, _ = _load_pim_yaml(HF_YAML)
        adapter = NiFiAdapter()
        result = adapter.convert(pim)
        qr = _get_processor_by_type(result, "QueryRecord")
        assert qr is not None, "Expected QueryRecord processor"
        sql = qr["properties"].get("filtered", "")
        # Adapter should produce non-Calcite "contains" — this is the known issue
        assert "contains" in sql.lower(), (
            f"Expected 'contains' in adapter SQL (known issue), got:\n{sql}"
        )

    def test_putfile_directory_is_filename(self):
        pim, _ = _load_pim_yaml(HF_YAML)
        adapter = NiFiAdapter()
        result = adapter.convert(pim)
        pf = _get_processor_by_type(result, "PutFile")
        assert pf is not None, "Expected PutFile processor"
        directory = pf["properties"].get("Directory", "")
        # Adapter puts the filename as Directory — this is the known issue
        assert directory.endswith(".csv"), (
            f"Expected a .csv filename as Directory (known issue), got: {directory!r}"
        )

    def test_uuids_are_valid_format(self):
        """Adapter UUIDs must be valid UUID4 strings."""
        import re
        uuid_re = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        )
        pim, _ = _load_pim_yaml(HF_YAML)
        adapter = NiFiAdapter()
        result = adapter.convert(pim)
        for p in result["flowContents"]["processors"]:
            uid = p["identifier"]
            assert uuid_re.match(uid), f"Invalid UUID format: {uid!r}"


# ---------------------------------------------------------------------------
# Integration tests (require Gemini API)
# ---------------------------------------------------------------------------

@requires_llm
class TestMode3LLMCorrector:
    """Verify that the LLM corrector fixes known semantic issues."""

    @pytest.fixture(scope="class")
    def corrected_result(self) -> dict:
        """Run the full Mode 3 pipeline once and share the result across tests."""
        pim, pim_yaml = _load_pim_yaml(HF_YAML)
        adapter = NiFiAdapter()
        adapter_dict = adapter.convert(pim)
        adapter_json = json.dumps(adapter_dict, indent=2, ensure_ascii=False)

        prompt = _build_corrector_prompt(pim_yaml, adapter_json)
        raw = _call_gemini_corrector(prompt)
        print(f"\n[mode3] raw response (first 300): {raw[:300]}")
        return _extract_json(raw)

    def test_query_record_uses_like_not_contains(self, corrected_result):
        qr = _get_processor_by_type(corrected_result, "QueryRecord")
        assert qr is not None, "QueryRecord processor missing from corrected output"
        sql = qr["properties"].get("filtered", "")
        assert "LIKE" in sql.upper(), f"Expected LIKE in corrected SQL, got:\n{sql}"
        assert "contains" not in sql.lower(), (
            f"'contains' should be replaced with LIKE, got:\n{sql}"
        )

    def test_null_checks_are_uppercase(self, corrected_result):
        qr = _get_processor_by_type(corrected_result, "QueryRecord")
        assert qr is not None
        sql = qr["properties"].get("filtered", "")
        assert "IS NOT NULL" in sql, f"Expected IS NOT NULL (uppercase), got:\n{sql}"
        assert "is not null" not in sql, f"Lowercase 'is not null' should be fixed"

    def test_putfile_directory_is_not_csv_filename(self, corrected_result):
        pf = _get_processor_by_type(corrected_result, "PutFile")
        assert pf is not None, "PutFile processor missing from corrected output"
        directory = pf["properties"].get("Directory", "")
        assert not directory.endswith(".csv"), (
            f"PutFile Directory should be a path, not a filename, got: {directory!r}"
        )

    def test_uuids_unchanged(self, corrected_result):
        """LLM must not alter processor UUIDs."""
        pim, _ = _load_pim_yaml(HF_YAML)
        adapter = NiFiAdapter()
        adapter_dict = adapter.convert(pim)
        original_ids = {p["identifier"] for p in adapter_dict["flowContents"]["processors"]}
        corrected_ids = {p["identifier"] for p in corrected_result["flowContents"]["processors"]}
        assert original_ids == corrected_ids, (
            f"LLM changed UUIDs!\n  original:  {original_ids}\n  corrected: {corrected_ids}"
        )

    def test_bundle_versions_unchanged(self, corrected_result):
        """LLM must not alter bundle versions."""
        pim, _ = _load_pim_yaml(HF_YAML)
        adapter = NiFiAdapter()
        adapter_dict = adapter.convert(pim)
        orig_bundles = {
            p["name"]: p["bundle"]
            for p in adapter_dict["flowContents"]["processors"]
        }
        corr_bundles = {
            p["name"]: p["bundle"]
            for p in corrected_result["flowContents"]["processors"]
        }
        assert orig_bundles == corr_bundles, (
            f"LLM changed bundle versions:\n  original:  {orig_bundles}\n  corrected: {corr_bundles}"
        )

    def test_processor_count_unchanged(self, corrected_result):
        """LLM must not add or remove processors."""
        pim, _ = _load_pim_yaml(HF_YAML)
        adapter = NiFiAdapter()
        adapter_dict = adapter.convert(pim)
        orig_count = len(adapter_dict["flowContents"]["processors"])
        corr_count = len(corrected_result["flowContents"]["processors"])
        assert orig_count == corr_count, (
            f"Processor count changed: {orig_count} → {corr_count}"
        )

    def test_connection_count_unchanged(self, corrected_result):
        """LLM must not add or remove connections."""
        pim, _ = _load_pim_yaml(HF_YAML)
        adapter = NiFiAdapter()
        adapter_dict = adapter.convert(pim)
        orig = len(adapter_dict["flowContents"]["connections"])
        corr = len(corrected_result["flowContents"]["connections"])
        assert orig == corr, f"Connection count changed: {orig} → {corr}"


# ---------------------------------------------------------------------------
# Prompt file sanity (no LLM)
# ---------------------------------------------------------------------------

class TestCorrectorPrompt:
    def test_prompt_file_exists(self):
        assert CORRECTOR_PROMPT_FILE.exists(), (
            f"nifi_corrector.txt not found at {CORRECTOR_PROMPT_FILE}"
        )

    def test_prompt_contains_placeholders(self):
        text = CORRECTOR_PROMPT_FILE.read_text(encoding="utf-8")
        assert "{pim_yaml}" in text, "Prompt must contain {pim_yaml} placeholder"
        assert "{nifi_json}" in text, "Prompt must contain {nifi_json} placeholder"

    def test_prompt_mentions_uuid_rule(self):
        text = CORRECTOR_PROMPT_FILE.read_text(encoding="utf-8")
        assert "identifier" in text.lower() or "uuid" in text.lower(), (
            "Prompt should mention UUID/identifier preservation rule"
        )
