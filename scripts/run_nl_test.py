"""
CLI: run the full NL→NiFi pipeline using the app's real backend
(Orchestrator + LLMService via EventBus). No raw API calls — uses the
same code path as the GUI.

Usage (single preset):
    python scripts/run_nl_test.py \\
        --query "Получай курс валют с exchangerate.host и пиши в файл rates.json" \\
        --preset 11 \\
        --mode 1

Usage (matrix — same query over multiple presets):
    python scripts/run_nl_test.py \\
        --query "..." \\
        --presets 11,13,14 \\
        --mode 3 \\
        --report matrix_report.json

Modes:
    0 — Direct      NL → LLM → NiFi JSON
    1 — Adapter     NL → LLM → YAML PIM → NiFiAdapter → NiFi JSON
    2 — LLM×2       NL → LLM → YAML PIM → LLM → NiFi JSON
    3 — Adapter+LLM NL → LLM → YAML PIM → NiFiAdapter → LLM correction → NiFi JSON

NiFi import (--nifi flag) reads credentials from env:
    NIFI_URL   (default: https://localhost:8443)
    NIFI_USER
    NIFI_PASS
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# src/ must be on path first so that `from main_logger import logger`
# (used inside src/core/events.py) resolves correctly.
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

# Suppress noisy backend logs by default (overridden with --verbose)
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

# --- Backend imports (order matters: events before services) ---
from src.core.events import EventBus, set_event_bus           # noqa: E402
from src.core.event_defines import Events                     # noqa: E402
from src.managers.settings_manager import SettingsManager     # noqa: E402
from src.services.db_service import init_db_service           # noqa: E402
from src.services.db_service import get_db_service            # noqa: E402
from src.services.llm_service import LLMService               # noqa: E402
from src.services.orchestrator import Orchestrator            # noqa: E402
from src.managers.api_preset_manager import ensure_api_presets_manager  # noqa: E402

# TOKENS_REPORTED event name (mirrors event_defines.py)
_EV_TOKENS = "model_tokens_reported"

MODE_NAMES = {
    0: "Direct (NL->JSON)",
    1: "Adapter (NL->YAML->JSON)",
    2: "LLMx2 (NL->YAML->LLM->JSON)",
    3: "Adapter+LLM (NL->YAML->Adapter->LLM->JSON)",
}

RUNS_ROOT = PROJECT_ROOT / "test_runs"


# ---------------------------------------------------------------------------
# Preset helpers
# ---------------------------------------------------------------------------

_BUILTIN_PRESETS = [
    {"id": 1, "name": "OpenAI",                      "default_model": "gpt-4o-mini",
     "url": "https://api.openai.com/v1/chat/completions", "key": ""},
    {"id": 2, "name": "DeepSeek (OpenAI-compatible)", "default_model": "deepseek-chat",
     "url": "https://api.deepseek.com/chat/completions",  "key": ""},
    {"id": 3, "name": "Ollama (local)",               "default_model": "llama3.1",
     "url": "http://localhost:11434/v1/chat/completions",  "key": ""},
    {"id": 4, "name": "OpenRouter",                   "default_model": "openai/gpt-4o-mini",
     "url": "https://openrouter.ai/api/v1/chat/completions", "key": ""},
]


def _load_presets() -> dict[str, dict]:
    """Return {str(id): preset_dict} from src/config/settings.json (app's real storage)."""
    path = PROJECT_ROOT / "src" / "config" / "settings.json"
    if not path.exists():
        print(f"ERROR: {path} not found. Run the app at least once.", file=sys.stderr)
        sys.exit(1)
    data = json.loads(path.read_text(encoding="utf-8"))

    result: dict[str, dict] = {}
    overrides = data.get("API_PRESETS_BUILTIN_OVERRIDES", {}) or {}
    for b in _BUILTIN_PRESETS:
        merged = dict(b)
        merged.update(overrides.get(str(b["id"]), {}) or {})
        result[str(b["id"])] = merged
    for p in data.get("API_PRESETS_CUSTOM", []) or []:
        if isinstance(p, dict) and "id" in p:
            result[str(p["id"])] = p
    return result


def _resolve_preset_id(preset_arg: str, presets: dict) -> int:
    """Resolve --preset value: numeric ID or case-insensitive name substring."""
    stripped = preset_arg.strip()
    try:
        pid = int(stripped)
        if str(pid) in presets:
            return pid
        raise ValueError(f"Preset ID {pid} not found. Run 'python scripts/list_presets.py'.")
    except ValueError as exc:
        if "not found" in str(exc):
            raise
    low = stripped.lower()
    for pid, p in presets.items():
        if low in (p.get("name") or "").lower():
            return int(pid)
    raise ValueError(
        f"No preset matching '{stripped}'. Run 'python scripts/list_presets.py' to see options."
    )


def _slug(text: str, max_len: int = 48) -> str:
    cleaned = []
    for ch in (text or "").lower():
        if ch.isalnum():
            cleaned.append(ch)
        elif ch in (" ", "-", "_", "/", "."):
            cleaned.append("-")
    slug = "".join(cleaned).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return (slug or "run")[:max_len].strip("-") or "run"


def _report_path(args, query: str, mode: int, preset_ids: list[int], presets: dict) -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    if args.report:
        raw = Path(args.report)
        if raw.is_absolute() or raw.parent != Path("."):
            return raw
        return RUNS_ROOT / "manual" / raw.name

    first = presets.get(str(preset_ids[0]), {})
    model = _slug(first.get("default_model", f"preset-{preset_ids[0]}"))
    case = _slug(query, max_len=64)
    return RUNS_ROOT / model / f"mode-{mode}" / case / f"{ts}.json"


# ---------------------------------------------------------------------------
# Backend init
# ---------------------------------------------------------------------------

def _init_backend() -> tuple[EventBus, Orchestrator]:
    import importlib as _il

    event_bus = EventBus()
    set_event_bus(event_bus)

    # Internal src/ modules use 'src.core.events' (different module object from 'core.events').
    # Sync both so all providers / managers share one EventBus.
    for _mod_name in ("core.events", "src.core.events"):
        try:
            _il.import_module(_mod_name).set_event_bus(event_bus)
        except Exception:
            pass

    settings_mgr = SettingsManager(str(PROJECT_ROOT / "src" / "config" / "settings.json"))

    # 'src.managers.settings_manager.SettingsManager' is a *separate* singleton class from
    # 'managers.settings_manager.SettingsManager' (dual sys.path import).  Patch its _instance
    # so that internal modules (api_preset_manager, etc.) get the already-initialized object
    # instead of creating a new one pointing at the wrong default config path.
    try:
        _il.import_module("src.managers.settings_manager").SettingsManager._instance = settings_mgr
    except Exception:
        pass

    init_db_service(str(PROJECT_ROOT / "src" / "config" / "flowarchitect.db"))
    llm_service = LLMService(settings=settings_mgr, event_bus=event_bus)
    orchestrator = Orchestrator(event_bus=event_bus, llm_service=llm_service)
    ensure_api_presets_manager()
    return event_bus, orchestrator


# ---------------------------------------------------------------------------
# NiFi import helper
# ---------------------------------------------------------------------------

def _nifi_import(nifi_json: dict, replace_existing: bool = False) -> dict:
    from src.services.nifi_client import NiFiClient  # lazy import (optional dep)

    url  = os.environ.get("NIFI_URL",  "https://localhost:8443")
    user = os.environ.get("NIFI_USER", "")
    pwd  = os.environ.get("NIFI_PASS", "")
    if not user or not pwd:
        return {"success": False, "error": "NIFI_USER/NIFI_PASS env vars not set", "pg_id": None,
                "validation_errors": [], "error_count": 0}

    client = NiFiClient(url, user, pwd)
    ok, msg = client.test_connection()
    if not ok:
        return {"success": False, "error": f"NiFi unreachable: {msg}", "pg_id": None,
                "validation_errors": [], "error_count": 0}

    import_ok, result = client.import_flow(nifi_json, replace_if_exists=replace_existing)
    if not import_ok:
        return {"success": False, "error": result, "pg_id": None,
                "validation_errors": [], "error_count": 0}

    pg_id = result
    client.enable_controller_services(pg_id)
    errors = client.get_validation_errors(pg_id)
    error_count = sum(len(e["errors"]) for e in errors)

    try:
        client.delete_pg(pg_id)
    except Exception:
        pass

    return {
        "success": True,
        "pg_id": pg_id,
        "validation_errors": errors,
        "error_count": error_count,
        "error": None,
        "replace_existing": replace_existing,
    }


# ---------------------------------------------------------------------------
# Pipeline runner (subscribes once, reusable across preset runs)
# ---------------------------------------------------------------------------

def _wait_with_progress(event: threading.Event, timeout: int, label: str) -> bool:
    """Wait for event, printing progress every 10s so the caller knows we're not hung."""
    start = time.time()
    while True:
        done = event.wait(timeout=10)
        if done:
            return True
        elapsed = int(time.time() - start)
        if elapsed >= timeout:
            return False
        print(f"  ... {label} ({elapsed}s elapsed, timeout={timeout}s)", flush=True)


class PipelineRunner:
    DEFAULT_TIMEOUT = 120  # seconds per stage

    def __init__(self, event_bus: EventBus, timeout: int = DEFAULT_TIMEOUT):
        self.event_bus = event_bus
        self.timeout = timeout

        self._yaml_ready  = threading.Event()
        self._json_ready  = threading.Event()
        self._error_ready = threading.Event()
        self._yaml: str | None = None
        self._json: str | None = None
        self._error: object = None

        # Token accumulator (reset per run)
        self._prompt_tokens:     int = 0
        self._completion_tokens: int = 0
        self._total_tokens:      int = 0
        self._session_id:        int | None = None

        # weak=False so the callbacks are not garbage-collected
        event_bus.subscribe(Events.Editor.UPDATE_CODE, self._on_update_code, weak=False)
        event_bus.subscribe(Events.Etl.ERROR,          self._on_error,       weak=False)
        event_bus.subscribe(_EV_TOKENS,                self._on_tokens,      weak=False)
        event_bus.subscribe(Events.Session.CREATED,     self._on_session_created, weak=False)

    def _on_update_code(self, event: object) -> None:
        payload = getattr(event, "data", event)
        if not isinstance(payload, dict):
            return
        kind = payload.get("kind")
        text = (payload.get("text") or payload.get("code") or "").strip()
        if not text:
            return
        if kind == "yaml":
            self._yaml = text
            self._yaml_ready.set()
        elif kind == "json":
            self._json = text
            self._json_ready.set()

    def _on_error(self, event: object) -> None:
        payload = getattr(event, "data", event)
        self._error = payload
        self._yaml_ready.set()
        self._json_ready.set()
        self._error_ready.set()

    def _on_tokens(self, event: object) -> None:
        payload = getattr(event, "data", event)
        if not isinstance(payload, dict):
            return
        self._prompt_tokens     += int(payload.get("prompt_tokens") or 0)
        self._completion_tokens += int(payload.get("completion_tokens") or 0)
        self._total_tokens      += int(payload.get("total_tokens") or 0)

    def _on_session_created(self, event: object) -> None:
        payload = getattr(event, "data", event)
        if isinstance(payload, dict) and isinstance(payload.get("session_id"), int):
            self._session_id = payload["session_id"]

    def _reset(self) -> None:
        self._yaml_ready.clear()
        self._json_ready.clear()
        self._error_ready.clear()
        self._yaml  = None
        self._json  = None
        self._error = None
        self._prompt_tokens     = 0
        self._completion_tokens = 0
        self._total_tokens      = 0
        self._session_id        = None

    def _collect_llm_analytics(self) -> tuple[list[dict], dict]:
        if self._session_id is None:
            return [], {}
        try:
            rows = get_db_service().get_llm_logs(self._session_id)
        except Exception:
            return [], {}

        calls: list[dict] = []
        summary: dict[str, dict] = {}
        for row in rows:
            prompt = int(row.get("prompt_tokens") or 0)
            completion = int(row.get("completion_tokens") or 0)
            cost = row.get("cost_usd")
            call = {
                "purpose": row.get("purpose"),
                "provider": row.get("provider"),
                "model": row.get("model"),
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": prompt + completion,
                "duration_ms": row.get("duration_ms"),
                "cost_usd": cost,
            }
            calls.append(call)

            key = str(row.get("purpose") or "unknown")
            bucket = summary.setdefault(key, {
                "calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "duration_ms": 0,
                "cost_usd": 0.0,
            })
            bucket["calls"] += 1
            bucket["prompt_tokens"] += prompt
            bucket["completion_tokens"] += completion
            bucket["total_tokens"] += prompt + completion
            bucket["duration_ms"] += int(row.get("duration_ms") or 0)
            if cost is not None:
                bucket["cost_usd"] += float(cost)

        for bucket in summary.values():
            bucket["cost_usd"] = round(bucket["cost_usd"], 6)
        return calls, summary

    def run(self, query: str, preset_id: int, mode: int, do_nifi: bool,
            preset_info: dict | None = None, stage_presets: dict | None = None,
            nifi_replace_existing: bool = True) -> dict:
        self._reset()
        t0 = time.time()
        ts = datetime.now(timezone.utc).isoformat()

        result: dict = {
            "timestamp":           ts,
            "success":             False,
            "yaml_pim":            None,
            "nifi_json":           None,
            "nifi_import":         None,
            "error":               None,
            "duration_sec":        0,
            "stage1_duration_sec": None,
            "stage2_duration_sec": None,
            # Token usage (accumulated from TOKENS_REPORTED events)
            "prompt_tokens":       None,
            "completion_tokens":   None,
            "total_tokens":        None,
            "cost_usd":            None,
            # NiFi structure (derived from nifi_json)
            "nifi_processor_count":  None,
            "nifi_connection_count": None,
            # PIM structure (derived from yaml_pim)
            "pim_source_count":      None,
            "pim_step_count":        None,
            "pim_sink_count":        None,
            "stage_presets":         stage_presets or {},
            "session_id":            None,
            "llm_calls":             [],
            "llm_usage_by_purpose":  {},
        }

        def elapsed() -> float:
            return round(time.time() - t0, 2)

        # ── Stage 1: USER_QUERY ──────────────────────────────────────────
        print(f"  [1/2] USER_QUERY  mode={mode}  preset={preset_id}", flush=True)
        t1 = time.time()
        self.event_bus.emit(Events.Etl.USER_QUERY, {
            "query":     query,
            "preset_id": preset_id,
            "mode":      mode,
        })

        if mode == Orchestrator.MODE_DIRECT:
            if not _wait_with_progress(self._json_ready, self.timeout, "waiting for NiFi JSON"):
                result["error"] = "timeout waiting for NiFi JSON (direct mode)"
                result["duration_sec"] = elapsed()
                return result
            result["stage1_duration_sec"] = round(time.time() - t1, 2)
        else:
            if not _wait_with_progress(self._yaml_ready, self.timeout, "waiting for YAML PIM"):
                result["error"] = "timeout waiting for YAML PIM"
                result["duration_sec"] = elapsed()
                return result

            result["stage1_duration_sec"] = round(time.time() - t1, 2)

            if self._error:
                result["error"] = self._error
                result["duration_sec"] = elapsed()
                return result

            result["yaml_pim"] = self._yaml
            print(f"  [1/2] PIM ready  ({len(self._yaml)} chars, {result['stage1_duration_sec']}s)", flush=True)

            # Parse PIM structure from YAML
            try:
                import yaml as _yaml
                pim_data = _yaml.safe_load(self._yaml)
                result["pim_source_count"] = len((pim_data or {}).get("sources", []) or [])
                result["pim_step_count"]   = len((pim_data or {}).get("processing_elements", []) or [])
                result["pim_sink_count"]   = len((pim_data or {}).get("sinks", []) or [])
            except Exception:
                pass

            # ── Stage 2: REQUEST_CONVERSION ──────────────────────────────
            print(f"  [2/2] REQUEST_CONVERSION  mode={mode}  preset={preset_id}", flush=True)
            t2 = time.time()
            self.event_bus.emit(Events.Etl.REQUEST_CONVERSION, {
                "yaml":      self._yaml,
                "mode":      mode,
                "preset_id": preset_id,
            })

            if not _wait_with_progress(self._json_ready, self.timeout, "waiting for NiFi JSON"):
                result["error"] = "timeout waiting for NiFi JSON"
                result["duration_sec"] = elapsed()
                return result

            result["stage2_duration_sec"] = round(time.time() - t2, 2)

        if self._error:
            result["error"] = self._error
            result["duration_sec"] = elapsed()
            return result

        # Parse JSON
        try:
            nifi_dict = json.loads(self._json)
        except Exception as exc:
            result["error"] = f"JSON parse error: {exc}"
            result["duration_sec"] = elapsed()
            return result

        result["nifi_json"] = nifi_dict
        # Derive NiFi structure metrics
        try:
            contents = nifi_dict.get("flowContents", nifi_dict)
            result["nifi_processor_count"]  = len(contents.get("processors", []) or [])
            result["nifi_connection_count"] = len(contents.get("connections", []) or [])
        except Exception:
            pass

        s2 = result.get("stage2_duration_sec", "?")
        print(f"  [2/2] NiFi JSON ready  "
              f"({result['nifi_processor_count']} proc, {result['nifi_connection_count']} conn, {s2}s)",
              flush=True)

        # ── Stage 3: optional NiFi import ───────────────────────────────
        if do_nifi:
            print(f"  [3/3] Importing to NiFi...", flush=True)
            nifi_result = _nifi_import(nifi_dict, replace_existing=nifi_replace_existing)
            result["nifi_import"] = nifi_result
            status = "OK" if nifi_result["success"] else f"FAILED: {nifi_result.get('error')}"
            print(f"  [3/3] NiFi import: {status}", flush=True)

        # ── Finalize tokens & cost ───────────────────────────────────────
        # Give background token events a moment to land (they fire async)
        time.sleep(0.3)
        if self._total_tokens or self._prompt_tokens or self._completion_tokens:
            result["prompt_tokens"]     = self._prompt_tokens
            result["completion_tokens"] = self._completion_tokens
            result["total_tokens"]      = self._total_tokens

            p_info = preset_info or {}
            price_in  = p_info.get("price_input_per_1m")
            price_out = p_info.get("price_output_per_1m")
            if price_in is not None and price_out is not None:
                try:
                    cost = (self._prompt_tokens * float(price_in) +
                            self._completion_tokens * float(price_out)) / 1_000_000
                    result["cost_usd"] = round(cost, 6)
                except Exception:
                    pass

            tok_msg = (f"  tokens: {self._prompt_tokens} in / "
                       f"{self._completion_tokens} out / "
                       f"{self._total_tokens} total")
            if result["cost_usd"] is not None:
                tok_msg += f"  |  cost: ${result['cost_usd']:.6f}"
            print(tok_msg, flush=True)

        calls, summary = self._collect_llm_analytics()
        result["session_id"] = self._session_id
        result["llm_calls"] = calls
        result["llm_usage_by_purpose"] = summary

        result["success"]      = True
        result["duration_sec"] = elapsed()
        return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run NL→NiFi pipeline via FlowArchitect backend. "
                    "Run 'python scripts/list_presets.py' to find preset IDs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    q_grp = parser.add_mutually_exclusive_group(required=True)
    q_grp.add_argument("--query",      "-q", metavar="TEXT",
                        help="Natural language pipeline description")
    q_grp.add_argument("--query-file", metavar="FILE",
                        help="Path to UTF-8 file containing the NL query")

    p_grp = parser.add_mutually_exclusive_group(required=True)
    p_grp.add_argument("--preset",  metavar="ID_OR_NAME",
                        help="Preset ID or name substring (single run)")
    p_grp.add_argument("--presets", metavar="ID1,ID2,...",
                        help="Comma-separated preset IDs for matrix run")

    parser.add_argument("--mode", type=int, default=3, choices=[0, 1, 2, 3],
                        help="Pipeline mode 0-3 (default: 3 = Adapter+LLM)")
    parser.add_argument("--nifi", action="store_true",
                        help="Import into NiFi (reads NIFI_URL/NIFI_USER/NIFI_PASS from env)")
    parser.add_argument("--nifi-keep-existing", action="store_true",
                        help="Do not replace an existing root-level process group with the same name")
    parser.add_argument("--out",     metavar="FILE",
                        help="Save NiFi JSON to file (only for single-preset runs)")
    parser.add_argument("--report",  metavar="FILE",
                        help="Save full test report as JSON")
    parser.add_argument("--timeout", type=int, default=120,
                        help="Per-stage timeout in seconds (default: 120)")
    parser.add_argument("--pim-preset", metavar="ID_OR_NAME",
                        help="Provider preset for NL -> PIM stage")
    parser.add_argument("--psm-preset", metavar="ID_OR_NAME",
                        help="Provider preset for YAML -> JSON LLM stage")
    parser.add_argument("--corrector-preset", metavar="ID_OR_NAME",
                        help="Provider preset for PIM and NiFi JSON correction stages")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show backend log output")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Load query
    query = (
        Path(args.query_file).read_text(encoding="utf-8").strip()
        if args.query_file
        else args.query
    )

    presets = _load_presets()

    # Resolve preset IDs
    if args.presets:
        preset_ids = [_resolve_preset_id(p, presets) for p in args.presets.split(",")]
    else:
        preset_ids = [_resolve_preset_id(args.preset, presets)]

    stage_preset_ids: dict[str, int] = {}
    if args.pim_preset:
        stage_preset_ids["pim"] = _resolve_preset_id(args.pim_preset, presets)
    if args.psm_preset:
        stage_preset_ids["psm"] = _resolve_preset_id(args.psm_preset, presets)
    if args.corrector_preset:
        cid = _resolve_preset_id(args.corrector_preset, presets)
        stage_preset_ids["error_corrector"] = cid
        stage_preset_ids["nifi_corrector"] = cid

    mode_label = MODE_NAMES.get(args.mode, str(args.mode))

    print()
    print("=" * 64)
    print(f"Query  : {query[:72]}{'...' if len(query) > 72 else ''}")
    print(f"Mode   : {args.mode} — {mode_label}")
    print(f"Presets: {preset_ids}")
    if args.nifi:
        print(f"NiFi   : {os.environ.get('NIFI_URL', 'https://localhost:8443')}")
    print("=" * 64)
    print()

    # Init backend (once, shared across all preset runs)
    print("Initialising backend...", flush=True)
    event_bus, _ = _init_backend()
    if stage_preset_ids:
        sm = SettingsManager(str(PROJECT_ROOT / "src" / "config" / "settings.json"))
        key_map = {
            "pim": "LLM_STAGE_PIM_PRESET_ID",
            "psm": "LLM_STAGE_PSM_PRESET_ID",
            "error_corrector": "LLM_STAGE_ERROR_CORRECTOR_PRESET_ID",
            "nifi_corrector": "LLM_STAGE_NIFI_CORRECTOR_PRESET_ID",
        }
        for stage, pid in stage_preset_ids.items():
            sm.set(key_map[stage], pid)
        print(f"Stage presets: {stage_preset_ids}", flush=True)
    runner = PipelineRunner(event_bus, timeout=args.timeout)
    print("Backend ready.\n", flush=True)

    report: dict = {
        "query":     query,
        "mode":      args.mode,
        "mode_name": mode_label,
        "runs":      [],
    }

    for preset_id in preset_ids:
        p_info  = presets.get(str(preset_id), {})
        p_name  = p_info.get("name", f"preset-{preset_id}")
        p_model = p_info.get("default_model", "?")

        print(f"--- Preset {preset_id}: {p_name}  [{p_model}] ---")

        run = runner.run(query=query, preset_id=preset_id, mode=args.mode,
                         do_nifi=args.nifi, preset_info=p_info, stage_presets=stage_preset_ids,
                         nifi_replace_existing=not args.nifi_keep_existing)
        run.update(preset_id=preset_id, preset_name=p_name, preset_model=p_model)
        report["runs"].append(run)

        ok_label = "[OK]" if run["success"] else f"[FAIL] {run.get('error')}"
        print(f"  Result : {ok_label}  ({run['duration_sec']}s)\n", flush=True)

        # Save NiFi JSON for single-preset runs
        if len(preset_ids) == 1 and args.out and run.get("nifi_json"):
            out_path = Path(args.out)
            out_path.write_text(
                json.dumps(run["nifi_json"], indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print(f"  NiFi JSON saved -> {out_path}", flush=True)

    # Summary
    total = len(report["runs"])
    ok    = sum(1 for r in report["runs"] if r["success"])
    print("=" * 64)
    print(f"Results: {ok}/{total} passed")
    print("=" * 64)

    rp = _report_path(args, query, args.mode, preset_ids, presets)
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReport saved -> {rp}")

    if len(preset_ids) > 1 and not args.report:
        print()
        print(json.dumps(report, indent=2, ensure_ascii=False))

    event_bus.shutdown()
    sys.exit(0 if ok == total else 1)


if __name__ == "__main__":
    main()
