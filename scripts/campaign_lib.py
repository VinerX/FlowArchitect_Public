from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
CAMPAIGNS_ROOT = PROJECT_ROOT / "test_runs" / "campaigns"
RAW_REPORT_NAME = "raw_report.json"
RUN_SUMMARY_NAME = "run_summary.json"
STATE_FILE_NAME = "campaign.json"
SUMMARY_CSV_NAME = "summary.csv"
NOTES_FILE_NAME = "notes.jsonl"
RUNNER_STDOUT_NAME = "runner_stdout.log"
RUNNER_STDERR_NAME = "runner_stderr.log"
RUN_REQUEST_NAME = "run_request.json"
QUERY_FILE_NAME = "query.txt"
PIM_FILE_NAME = "pim.yaml"
NIFI_FILE_NAME = "nifi.json"
STATUS_VALUES = {
    "queued",
    "running",
    "needs_user_input",
    "needs_nifi_manual_test",
    "completed",
    "failed_generation",
    "failed_import",
    "cancelled",
}
DEFAULT_STOP_STATUSES = ["needs_user_input", "needs_nifi_manual_test"]
SUMMARY_COLUMNS = [
    "run_id",
    "case_id",
    "title",
    "attempt",
    "mode",
    "preset_id",
    "preset_name",
    "preset_model",
    "status",
    "duration_sec",
    "stage1_duration_sec",
    "stage2_duration_sec",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cost_usd",
    "nifi_validate",
    "nifi_import_success",
    "nifi_error_count",
    "manual_nifi_required",
    "requires_user_input",
    "comment_count",
    "started_at",
    "finished_at",
    "report_path",
]

TEMPLATE_MANIFEST = """\
campaign:
  id: thesis-global-validation-202605
  title: Глобальная серия валидации для ВКР
  owner: Дмитрий Макаров
  objective: >
    Сравнить режимы 0, 1 и 3 на фиксированном наборе кейсов и собрать
    артефакты для анализа качества, устойчивости и экономии времени.
  tags:
    - thesis
    - global-validation

defaults:
  presets:
    - 1000
  modes:
    - 0
    - 1
    - 3
  stage_presets:
    pim: 1000
    corrector: 1003
  repeat: 1
  timeout_sec: 300
  nifi_validate: true
  manual_nifi_required: true
  requires_user_input: false
  stop_after_statuses:
    - needs_user_input
    - needs_nifi_manual_test

cases:
  - id: currency-http-to-file
    title: Получение курсов валют в файл
    query: >
      Получай курсы валют с https://api.exchangerate.host/latest и сохраняй
      результат в файл rates.json.
    tags:
      - http
      - file
      - baseline
    expected_behavior: Файл rates.json должен обновляться по расписанию.
    manual_test_checklist:
      - Импортировать сохраненный nifi.json в тестовый NiFi.
      - Проверить, что flow проходит валидацию и пишет файл.

  - id: kafka-to-postgres
    title: Kafka в PostgreSQL
    query: >
      Считывай сообщения из Kafka topic orders, преобразуй JSON в строки
      таблицы и записывай их в PostgreSQL.
    tags:
      - kafka
      - postgres
      - streaming

  - id: postgres-to-kafka
    title: PostgreSQL в Kafka
    query: >
      Периодически выбирай новые записи из PostgreSQL и публикуй их в Kafka
      topic analytics.events в формате JSON.
    tags:
      - postgres
      - kafka
      - batch

  - id: s3-to-hdfs
    title: S3 в HDFS
    query: >
      Забирай файлы из S3 бакета raw-data, при необходимости распаковывай их
      и складывай в HDFS в каталог /data/raw.
    tags:
      - s3
      - hdfs
      - file-transfer
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(text: str, max_len: int = 64) -> str:
    chars: list[str] = []
    for ch in (text or "").lower():
        if ch.isalnum():
            chars.append(ch)
        elif ch in {" ", "-", "_", ".", "/"}:
            chars.append("-")
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug[:max_len].strip("-")
    return slug or "campaign"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_yaml(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def resolve_campaign_dir(ref: str) -> Path:
    raw = Path(ref)
    if raw.exists():
        return raw.resolve()
    return (CAMPAIGNS_ROOT / ref).resolve()


def load_manifest(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("Manifest must be a YAML mapping at the root.")
    return payload


def normalize_stage_presets(raw: dict[str, Any] | None) -> dict[str, int]:
    raw = raw or {}
    normalized: dict[str, int] = {}

    def _to_int(name: str, value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Stage preset '{name}' must be an integer preset ID.") from exc

    if "pim" in raw and raw["pim"] is not None:
        normalized["pim"] = _to_int("pim", raw["pim"])
    if "psm" in raw and raw["psm"] is not None:
        normalized["psm"] = _to_int("psm", raw["psm"])

    corrector = raw.get("corrector")
    error_corrector = raw.get("error_corrector")
    nifi_corrector = raw.get("nifi_corrector")
    candidates = [v for v in (corrector, error_corrector, nifi_corrector) if v is not None]
    if candidates:
        first = _to_int("corrector", candidates[0])
        for other in candidates[1:]:
            if _to_int("corrector", other) != first:
                raise ValueError(
                    "Current run_nl_test.py supports one shared corrector preset. "
                    "Use 'corrector' or keep error_corrector/nifi_corrector equal."
                )
        normalized["corrector"] = first

    unsupported = set(raw) - {"pim", "psm", "corrector", "error_corrector", "nifi_corrector"}
    if unsupported:
        names = ", ".join(sorted(unsupported))
        raise ValueError(f"Unsupported stage preset keys: {names}")
    return normalized


def _as_list(value: Any, field_name: str) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    raise ValueError(f"Field '{field_name}' must be a list.")


def _coerce_bool(value: Any, field_name: str, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ValueError(f"Field '{field_name}' must be true/false.")


def _coerce_int(value: Any, field_name: str, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Field '{field_name}' must be an integer.") from exc


def _stage_hash(stage_presets: dict[str, int]) -> str:
    if not stage_presets:
        return "default"
    encoded = json.dumps(stage_presets, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:8]


def build_run_id(
    case_id: str,
    mode: int,
    preset_id: int,
    attempt: int,
    stage_presets: dict[str, int],
) -> str:
    return (
        f"{case_id}__m{mode}__p{preset_id}__a{attempt}__sp{_stage_hash(stage_presets)}"
    )


def expand_manifest(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    campaign = manifest.get("campaign") or {}
    defaults = manifest.get("defaults") or {}
    cases = manifest.get("cases") or []

    if not isinstance(campaign, dict):
        raise ValueError("Manifest field 'campaign' must be a mapping.")
    if not isinstance(defaults, dict):
        raise ValueError("Manifest field 'defaults' must be a mapping.")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Manifest field 'cases' must be a non-empty list.")

    campaign_id = slugify(str(campaign.get("id") or manifest_path.stem))
    campaign_title = str(campaign.get("title") or campaign_id)
    default_presets = [int(v) for v in _as_list(defaults.get("presets"), "defaults.presets")]
    default_modes = [int(v) for v in _as_list(defaults.get("modes"), "defaults.modes")]
    if not default_presets:
        raise ValueError("defaults.presets must contain at least one preset ID.")
    if not default_modes:
        raise ValueError("defaults.modes must contain at least one mode.")

    default_stage_presets = normalize_stage_presets(defaults.get("stage_presets"))
    default_repeat = _coerce_int(defaults.get("repeat"), "defaults.repeat", 1)
    default_timeout = _coerce_int(defaults.get("timeout_sec"), "defaults.timeout_sec", 120)
    default_nifi_validate = _coerce_bool(
        defaults.get("nifi_validate"), "defaults.nifi_validate", True
    )
    default_manual_nifi = _coerce_bool(
        defaults.get("manual_nifi_required"), "defaults.manual_nifi_required", False
    )
    default_requires_input = _coerce_bool(
        defaults.get("requires_user_input"), "defaults.requires_user_input", False
    )
    stop_after_statuses = defaults.get("stop_after_statuses") or DEFAULT_STOP_STATUSES
    stop_after_statuses = [str(v) for v in _as_list(stop_after_statuses, "defaults.stop_after_statuses")]
    for status in stop_after_statuses:
        if status not in STATUS_VALUES:
            raise ValueError(f"Unknown stop_after_statuses value: {status}")

    run_records: list[dict[str, Any]] = []
    run_ids: set[str] = set()
    case_ids: set[str] = set()

    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"Case at index {index} must be a mapping.")
        case_id = slugify(str(case.get("id") or f"case-{index + 1}"))
        if case_id in case_ids:
            raise ValueError(f"Duplicate case id: {case_id}")
        case_ids.add(case_id)

        title = str(case.get("title") or case_id)
        query = case.get("query")
        query_file = case.get("query_file")
        if query is None and query_file is None:
            raise ValueError(f"Case '{case_id}' must define 'query' or 'query_file'.")
        if query is not None and not str(query).strip():
            raise ValueError(f"Case '{case_id}' has an empty 'query'.")
        resolved_query_file: str | None = None
        if query_file is not None:
            qf = (manifest_path.parent / str(query_file)).resolve()
            if not qf.exists():
                raise ValueError(f"Case '{case_id}' query_file not found: {qf}")
            resolved_query_file = str(qf)

        presets = [int(v) for v in _as_list(case.get("presets", default_presets), f"{case_id}.presets")]
        modes = [int(v) for v in _as_list(case.get("modes", default_modes), f"{case_id}.modes")]
        repeat = _coerce_int(case.get("repeat"), f"{case_id}.repeat", default_repeat)
        timeout_sec = _coerce_int(case.get("timeout_sec"), f"{case_id}.timeout_sec", default_timeout)
        nifi_validate = _coerce_bool(case.get("nifi_validate"), f"{case_id}.nifi_validate", default_nifi_validate)
        manual_nifi_required = _coerce_bool(
            case.get("manual_nifi_required"),
            f"{case_id}.manual_nifi_required",
            default_manual_nifi,
        )
        requires_user_input = _coerce_bool(
            case.get("requires_user_input"),
            f"{case_id}.requires_user_input",
            default_requires_input,
        )
        stage_presets = deepcopy(default_stage_presets)
        stage_presets.update(normalize_stage_presets(case.get("stage_presets")))
        extra_metadata = {
            key: value
            for key, value in case.items()
            if key
            not in {
                "id",
                "title",
                "query",
                "query_file",
                "presets",
                "modes",
                "repeat",
                "timeout_sec",
                "nifi_validate",
                "manual_nifi_required",
                "requires_user_input",
                "stage_presets",
            }
        }

        for preset_id in presets:
            for mode in modes:
                for attempt in range(1, repeat + 1):
                    run_id = build_run_id(case_id, mode, preset_id, attempt, stage_presets)
                    if run_id in run_ids:
                        raise ValueError(f"Duplicate run id produced by manifest: {run_id}")
                    run_ids.add(run_id)
                    run_records.append(
                        {
                            "run_id": run_id,
                            "case_id": case_id,
                            "title": title,
                            "query": str(query).strip() if query is not None else None,
                            "query_file": resolved_query_file,
                            "attempt": attempt,
                            "mode": int(mode),
                            "preset_id": int(preset_id),
                            "stage_presets": stage_presets,
                            "timeout_sec": timeout_sec,
                            "nifi_validate": nifi_validate,
                            "manual_nifi_required": manual_nifi_required,
                            "requires_user_input": requires_user_input,
                            "extra_metadata": extra_metadata,
                            "status": "queued",
                            "comment_count": 0,
                            "history": [
                                {
                                    "timestamp": utc_now(),
                                    "status": "queued",
                                    "reason": "campaign_init",
                                }
                            ],
                        }
                    )

    return {
        "campaign_id": campaign_id,
        "campaign_title": campaign_title,
        "campaign_meta": campaign,
        "defaults": {
            "presets": default_presets,
            "modes": default_modes,
            "stage_presets": default_stage_presets,
            "repeat": default_repeat,
            "timeout_sec": default_timeout,
            "nifi_validate": default_nifi_validate,
            "manual_nifi_required": default_manual_nifi,
            "requires_user_input": default_requires_input,
            "stop_after_statuses": stop_after_statuses,
        },
        "runs": run_records,
    }


def create_campaign_state(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    expanded = expand_manifest(manifest, manifest_path)
    created_at = utc_now()
    return {
        "schema_version": 1,
        "created_at": created_at,
        "updated_at": created_at,
        "campaign": {
            "id": expanded["campaign_id"],
            "title": expanded["campaign_title"],
            "meta": expanded["campaign_meta"],
            "manifest_source": str(manifest_path.resolve()),
        },
        "defaults": expanded["defaults"],
        "run_order": [run["run_id"] for run in expanded["runs"]],
        "runs": {run["run_id"]: run for run in expanded["runs"]},
        "status_counts": {},
    }


def merge_manifest_into_state(
    state: dict[str, Any],
    manifest: dict[str, Any],
    manifest_path: Path,
) -> dict[str, Any]:
    expanded = expand_manifest(manifest, manifest_path)
    existing_run_ids = set(state["runs"].keys())
    expanded_runs = {run["run_id"]: run for run in expanded["runs"]}
    added_run_ids: list[str] = []

    for run_id, run in expanded_runs.items():
        if run_id not in existing_run_ids:
            state["runs"][run_id] = run
            added_run_ids.append(run_id)

    ordered_ids: list[str] = []
    for run in expanded["runs"]:
        run_id = run["run_id"]
        if run_id in state["runs"]:
            ordered_ids.append(run_id)
    for run_id in state["run_order"]:
        if run_id not in expanded_runs:
            ordered_ids.append(run_id)
    state["run_order"] = ordered_ids

    state["campaign"]["meta"] = expanded["campaign_meta"]
    state["campaign"]["title"] = expanded["campaign_title"]
    state["campaign"]["manifest_source"] = str(manifest_path.resolve())
    state["defaults"] = expanded["defaults"]

    return {
        "added_run_ids": added_run_ids,
        "manifest_campaign_id": expanded["campaign_id"],
        "manifest_title": expanded["campaign_title"],
        "total_runs_after_sync": len(state["run_order"]),
    }


def compute_status_counts(state: dict[str, Any]) -> dict[str, int]:
    counts = {status: 0 for status in STATUS_VALUES}
    for run in state["runs"].values():
        counts[run["status"]] = counts.get(run["status"], 0) + 1
    return {status: count for status, count in counts.items() if count}


def summary_row(run: dict[str, Any]) -> dict[str, Any]:
    result = run.get("result_summary") or {}
    row = {
        "run_id": run["run_id"],
        "case_id": run["case_id"],
        "title": run.get("title"),
        "attempt": run.get("attempt"),
        "mode": run.get("mode"),
        "preset_id": run.get("preset_id"),
        "preset_name": result.get("preset_name"),
        "preset_model": result.get("preset_model"),
        "status": run.get("status"),
        "duration_sec": result.get("duration_sec"),
        "stage1_duration_sec": result.get("stage1_duration_sec"),
        "stage2_duration_sec": result.get("stage2_duration_sec"),
        "prompt_tokens": result.get("prompt_tokens"),
        "completion_tokens": result.get("completion_tokens"),
        "total_tokens": result.get("total_tokens"),
        "cost_usd": result.get("cost_usd"),
        "nifi_validate": run.get("nifi_validate"),
        "nifi_import_success": result.get("nifi_import_success"),
        "nifi_error_count": result.get("nifi_error_count"),
        "manual_nifi_required": run.get("manual_nifi_required"),
        "requires_user_input": run.get("requires_user_input"),
        "comment_count": run.get("comment_count", 0),
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "report_path": run.get("report_path"),
    }
    return row


def export_summary_csv(campaign_dir: Path, state: dict[str, Any]) -> None:
    rows = [summary_row(state["runs"][run_id]) for run_id in state["run_order"]]
    path = campaign_dir / SUMMARY_CSV_NAME
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def save_state(campaign_dir: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now()
    state["status_counts"] = compute_status_counts(state)
    write_json(campaign_dir / STATE_FILE_NAME, state)
    try:
        export_summary_csv(campaign_dir, state)
    except PermissionError:
        # Keep campaign progress durable even if a CSV viewer temporarily locks the file.
        pass


def load_state(campaign_dir: Path) -> dict[str, Any]:
    state_path = campaign_dir / STATE_FILE_NAME
    if not state_path.exists():
        raise FileNotFoundError(f"Campaign state not found: {state_path}")
    return read_json(state_path)


def _load_nifi_settings() -> dict[str, Any]:
    settings_path = PROJECT_ROOT / "config" / "settings.json"
    if not settings_path.exists():
        return {}
    try:
        return read_json(settings_path)
    except Exception:
        return {}


def _resolve_nifi_credentials() -> tuple[str, str, str]:
    settings = _load_nifi_settings()
    url = os.environ.get("NIFI_URL") or settings.get("nifi_url") or "https://localhost:8443"
    user = os.environ.get("NIFI_USER") or settings.get("nifi_username") or ""
    pwd = os.environ.get("NIFI_PASS") or settings.get("nifi_password") or ""
    if not user or not pwd:
        raise RuntimeError(
            "NiFi credentials are missing. Set NIFI_URL/NIFI_USER/NIFI_PASS "
            "or configure them in config/settings.json."
        )
    return str(url), str(user), str(pwd)


def _nifi_client():
    from src.services.nifi_client import NiFiClient

    url, user, pwd = _resolve_nifi_credentials()
    return NiFiClient(url, user, pwd)


def initialize_campaign(manifest_path: Path, campaign_id: str | None = None, force: bool = False) -> Path:
    manifest = load_manifest(manifest_path)
    state = create_campaign_state(manifest, manifest_path)
    if campaign_id:
        normalized_id = slugify(campaign_id)
        state["campaign"]["id"] = normalized_id
        state["campaign"]["meta"]["id"] = normalized_id
    campaign_dir = CAMPAIGNS_ROOT / state["campaign"]["id"]
    if campaign_dir.exists():
        if not force:
            raise FileExistsError(
                f"Campaign directory already exists: {campaign_dir}. Use --force to recreate it."
            )
        shutil.rmtree(campaign_dir)
    campaign_dir.mkdir(parents=True, exist_ok=True)
    write_yaml(campaign_dir / "manifest.snapshot.yaml", manifest)
    save_state(campaign_dir, state)
    return campaign_dir


def sync_campaign_with_manifest(campaign_dir: Path, manifest_path: Path) -> dict[str, Any]:
    state = load_state(campaign_dir)
    manifest = load_manifest(manifest_path)
    result = merge_manifest_into_state(state, manifest, manifest_path)
    save_state(campaign_dir, state)
    return result


def _manual_test_checklist(run: dict[str, Any]) -> list[str]:
    checklist = run.get("extra_metadata", {}).get("manual_test_checklist") or []
    return [str(item) for item in checklist]


def materialize_run_in_nifi(campaign_dir: Path, run_id: str, replace_existing: bool = False) -> dict[str, Any]:
    state = load_state(campaign_dir)
    if run_id not in state["runs"]:
        raise KeyError(f"Unknown run_id: {run_id}")
    run = state["runs"][run_id]
    run_dir = campaign_dir / "runs" / run_id
    nifi_path = run_dir / NIFI_FILE_NAME
    if not nifi_path.exists():
        raise FileNotFoundError(f"Run does not have a saved nifi.json: {nifi_path}")

    flow_json = read_json(nifi_path)
    client = _nifi_client()
    ok, msg = client.test_connection()
    if not ok:
        raise RuntimeError(f"Cannot connect to NiFi: {msg}")

    import_ok, import_result = client.import_flow(flow_json, replace_if_exists=replace_existing)
    if not import_ok:
        raise RuntimeError(import_result)

    pg_id = import_result
    enabled_services = client.enable_controller_services(pg_id)
    validation_errors = client.get_validation_errors(pg_id)

    run["manual_nifi_pg_id"] = pg_id
    run["manual_nifi_materialized_at"] = utc_now()
    run["manual_nifi_replace_existing"] = bool(replace_existing)
    run["manual_nifi_enabled_controller_services"] = enabled_services
    run["manual_nifi_validation_errors"] = validation_errors
    run["manual_nifi_validation_error_count"] = sum(len(x.get("errors", [])) for x in validation_errors)
    run["manual_nifi_connection_info"] = msg
    append_note(
        campaign_dir=campaign_dir,
        state=state,
        author="Codex",
        kind="manual_nifi_materialized",
        text=(
            f"Run materialized into NiFi for manual inspection. "
            f"pg_id={pg_id}, validation_errors={run['manual_nifi_validation_error_count']}."
        ),
        run_id=run_id,
    )

    return {
        "run_id": run_id,
        "pg_id": pg_id,
        "connection_info": msg,
        "enabled_controller_services": enabled_services,
        "validation_errors": validation_errors,
        "validation_error_count": run["manual_nifi_validation_error_count"],
        "checklist": _manual_test_checklist(run),
        "nifi_json_path": str(nifi_path),
    }


def cleanup_materialized_run(campaign_dir: Path, run_id: str) -> dict[str, Any]:
    state = load_state(campaign_dir)
    if run_id not in state["runs"]:
        raise KeyError(f"Unknown run_id: {run_id}")
    run = state["runs"][run_id]
    pg_id = run.get("manual_nifi_pg_id")
    if not pg_id:
        raise RuntimeError(f"Run {run_id} does not have a recorded manual_nifi_pg_id.")

    client = _nifi_client()
    ok, msg = client.test_connection()
    if not ok:
        raise RuntimeError(f"Cannot connect to NiFi: {msg}")

    client.delete_pg(str(pg_id))
    run["manual_nifi_cleaned_at"] = utc_now()
    append_note(
        campaign_dir=campaign_dir,
        state=state,
        author="Codex",
        kind="manual_nifi_cleanup",
        text=f"Deleted materialized NiFi process group {pg_id}.",
        run_id=run_id,
    )
    return {
        "run_id": run_id,
        "deleted_pg_id": pg_id,
        "connection_info": msg,
    }


def _command_timeout(run: dict[str, Any]) -> int:
    timeout_sec = int(run.get("timeout_sec") or 120)
    return max(300, timeout_sec * 3 + 60)


def _build_run_command(run: dict[str, Any], python_executable: str, run_dir: Path) -> list[str]:
    query_path = run_dir / QUERY_FILE_NAME
    cmd = [
        python_executable,
        str(PROJECT_ROOT / "scripts" / "run_nl_test.py"),
        "--query-file",
        str(query_path),
        "--preset",
        str(run["preset_id"]),
        "--mode",
        str(run["mode"]),
        "--timeout",
        str(run["timeout_sec"]),
        "--report",
        str(run_dir / RAW_REPORT_NAME),
    ]
    stage_presets = run.get("stage_presets") or {}
    if "pim" in stage_presets:
        cmd.extend(["--pim-preset", str(stage_presets["pim"])])
    if "psm" in stage_presets:
        cmd.extend(["--psm-preset", str(stage_presets["psm"])])
    if "corrector" in stage_presets:
        cmd.extend(["--corrector-preset", str(stage_presets["corrector"])])
    if run.get("nifi_validate"):
        cmd.append("--nifi")
    return cmd


def _load_query_text(run: dict[str, Any]) -> str:
    if run.get("query") is not None:
        return str(run["query"]).strip()
    query_file = Path(str(run["query_file"]))
    return query_file.read_text(encoding="utf-8").strip()


def _condense_run_report(run_payload: dict[str, Any]) -> dict[str, Any]:
    success = bool(run_payload.get("success"))
    nifi_import = run_payload.get("nifi_import") or {}
    return {
        "success": success,
        "error": run_payload.get("error"),
        "duration_sec": run_payload.get("duration_sec"),
        "stage1_duration_sec": run_payload.get("stage1_duration_sec"),
        "stage2_duration_sec": run_payload.get("stage2_duration_sec"),
        "prompt_tokens": run_payload.get("prompt_tokens"),
        "completion_tokens": run_payload.get("completion_tokens"),
        "total_tokens": run_payload.get("total_tokens"),
        "cost_usd": run_payload.get("cost_usd"),
        "nifi_processor_count": run_payload.get("nifi_processor_count"),
        "nifi_connection_count": run_payload.get("nifi_connection_count"),
        "pim_source_count": run_payload.get("pim_source_count"),
        "pim_step_count": run_payload.get("pim_step_count"),
        "pim_sink_count": run_payload.get("pim_sink_count"),
        "session_id": run_payload.get("session_id"),
        "preset_id": run_payload.get("preset_id"),
        "preset_name": run_payload.get("preset_name"),
        "preset_model": run_payload.get("preset_model"),
        "llm_calls": run_payload.get("llm_calls") or [],
        "llm_usage_by_purpose": run_payload.get("llm_usage_by_purpose") or {},
        "nifi_import_success": nifi_import.get("success"),
        "nifi_error_count": nifi_import.get("error_count"),
        "nifi_import_error": nifi_import.get("error"),
    }


def derive_run_status(run: dict[str, Any], run_payload: dict[str, Any]) -> str:
    if not run_payload.get("success"):
        return "failed_generation"

    if run.get("nifi_validate"):
        nifi_import = run_payload.get("nifi_import") or {}
        if not nifi_import.get("success"):
            return "failed_import"
        if int(nifi_import.get("error_count") or 0) > 0:
            return "failed_import"

    if run.get("requires_user_input"):
        return "needs_user_input"
    if run.get("manual_nifi_required"):
        return "needs_nifi_manual_test"
    return "completed"


def _write_run_artifacts(run_dir: Path, raw_report: dict[str, Any]) -> None:
    runs = raw_report.get("runs") or []
    run_payload = runs[0] if runs else {}
    if run_payload.get("yaml_pim"):
        (run_dir / PIM_FILE_NAME).write_text(str(run_payload["yaml_pim"]), encoding="utf-8")
    if run_payload.get("nifi_json") is not None:
        write_json(run_dir / NIFI_FILE_NAME, run_payload["nifi_json"])


def _update_status(run: dict[str, Any], new_status: str, reason: str) -> None:
    if new_status not in STATUS_VALUES:
        raise ValueError(f"Unknown status: {new_status}")
    run["status"] = new_status
    run.setdefault("history", []).append(
        {"timestamp": utc_now(), "status": new_status, "reason": reason}
    )


def append_note(
    campaign_dir: Path,
    state: dict[str, Any],
    author: str,
    kind: str,
    text: str,
    run_id: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    if run_id is not None and run_id not in state["runs"]:
        raise KeyError(f"Unknown run_id: {run_id}")
    note = {
        "timestamp": utc_now(),
        "author": author,
        "kind": kind,
        "text": text,
        "run_id": run_id,
    }
    append_jsonl(campaign_dir / NOTES_FILE_NAME, note)
    if run_id is not None:
        run = state["runs"][run_id]
        run_dir = campaign_dir / "runs" / run_id
        append_jsonl(run_dir / NOTES_FILE_NAME, note)
        run["comment_count"] = int(run.get("comment_count") or 0) + 1
        run["last_comment_at"] = note["timestamp"]
        if status:
            _update_status(run, status, f"note:{kind}")
    save_state(campaign_dir, state)
    return note


def _run_ids_by_filter(
    state: dict[str, Any],
    include_statuses: list[str],
    run_id: str | None,
    case_id: str | None,
) -> list[str]:
    selected: list[str] = []
    for current_id in state["run_order"]:
        run = state["runs"][current_id]
        if include_statuses and run["status"] not in include_statuses:
            continue
        if run_id and current_id != run_id:
            continue
        if case_id and run["case_id"] != case_id:
            continue
        selected.append(current_id)
    return selected


def execute_campaign_runs(
    campaign_dir: Path,
    limit: int | None = None,
    include_statuses: list[str] | None = None,
    run_id: str | None = None,
    case_id: str | None = None,
    python_executable: str | None = None,
    stop_on_statuses: list[str] | None = None,
) -> dict[str, Any]:
    state = load_state(campaign_dir)
    include_statuses = include_statuses or ["queued"]
    stop_on_statuses = stop_on_statuses or state["defaults"].get("stop_after_statuses") or DEFAULT_STOP_STATUSES
    python_executable = python_executable or sys.executable
    selected = _run_ids_by_filter(state, include_statuses, run_id, case_id)
    if limit is not None:
        selected = selected[:limit]

    processed: list[dict[str, Any]] = []
    halted_on: dict[str, Any] | None = None

    for current_id in selected:
        run = state["runs"][current_id]
        run_dir = campaign_dir / "runs" / current_id
        run_dir.mkdir(parents=True, exist_ok=True)
        query_text = _load_query_text(run)
        (run_dir / QUERY_FILE_NAME).write_text(query_text + "\n", encoding="utf-8")

        run["started_at"] = utc_now()
        _update_status(run, "running", "runner_started")
        save_state(campaign_dir, state)

        command = _build_run_command(run, python_executable, run_dir)
        run["command"] = command
        run["python_executable"] = python_executable
        run["command_timeout_sec"] = _command_timeout(run)
        write_json(run_dir / RUN_REQUEST_NAME, run)
        save_state(campaign_dir, state)
        try:
            completed = subprocess.run(
                command,
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=run["command_timeout_sec"],
            )
            stdout_text = completed.stdout or ""
            stderr_text = completed.stderr or ""
            exit_code = completed.returncode
        except subprocess.TimeoutExpired as exc:
            stdout_text = exc.stdout or ""
            stderr_text = (exc.stderr or "") + "\nCampaign runner timeout expired."
            exit_code = -1

        (run_dir / RUNNER_STDOUT_NAME).write_text(stdout_text, encoding="utf-8")
        (run_dir / RUNNER_STDERR_NAME).write_text(stderr_text, encoding="utf-8")

        run["finished_at"] = utc_now()
        run["exit_code"] = exit_code
        run["report_path"] = str(run_dir / RAW_REPORT_NAME)
        run["stdout_path"] = str(run_dir / RUNNER_STDOUT_NAME)
        run["stderr_path"] = str(run_dir / RUNNER_STDERR_NAME)
        run["query_path"] = str(run_dir / QUERY_FILE_NAME)

        raw_report_path = run_dir / RAW_REPORT_NAME
        if raw_report_path.exists():
            raw_report = read_json(raw_report_path)
            runs = raw_report.get("runs") or []
            run_payload = runs[0] if runs else {}
            _write_run_artifacts(run_dir, raw_report)
            run["result_summary"] = _condense_run_report(run_payload)
            final_status = derive_run_status(run, run_payload)
        else:
            run["result_summary"] = {
                "success": False,
                "error": (
                    "run_nl_test.py did not produce a report file."
                    if exit_code != -1
                    else "run_nl_test.py exceeded campaign runner timeout."
                ),
            }
            final_status = "failed_generation"

        if exit_code != 0 and run["result_summary"].get("success"):
            run["result_summary"]["warning"] = (
                "Runner exited with non-zero code despite a successful run payload."
            )

        write_json(run_dir / RUN_SUMMARY_NAME, run["result_summary"])
        run["summary_path"] = str(run_dir / RUN_SUMMARY_NAME)
        _update_status(run, final_status, "runner_finished")
        save_state(campaign_dir, state)

        processed.append(
            {
                "run_id": current_id,
                "status": final_status,
                "report_path": run["report_path"],
                "summary_path": run["summary_path"],
            }
        )

        if final_status in stop_on_statuses:
            halted_on = processed[-1]
            break

    return {
        "processed": processed,
        "halted_on": halted_on,
        "remaining_queued": compute_status_counts(load_state(campaign_dir)).get("queued", 0),
    }


def set_run_status(
    campaign_dir: Path,
    run_id: str,
    status: str,
    author: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    state = load_state(campaign_dir)
    if status not in STATUS_VALUES:
        raise ValueError(f"Unknown status: {status}")
    if run_id not in state["runs"]:
        raise KeyError(f"Unknown run_id: {run_id}")
    run = state["runs"][run_id]
    _update_status(run, status, "manual_status_change")
    if note:
        append_note(
            campaign_dir=campaign_dir,
            state=state,
            author=author or "operator",
            kind="status_change_note",
            text=note,
            run_id=run_id,
        )
    else:
        save_state(campaign_dir, state)
    return run


def format_status_text(campaign_dir: Path, state: dict[str, Any], verbose: bool = False) -> str:
    counts = compute_status_counts(state)
    lines = [
        f"Campaign: {state['campaign']['id']}",
        f"Title: {state['campaign']['title']}",
        f"Directory: {campaign_dir}",
        f"Runs total: {len(state['run_order'])}",
        "Status counts: " + ", ".join(f"{name}={count}" for name, count in sorted(counts.items())),
    ]
    if verbose:
        lines.append("")
        for run_id in state["run_order"]:
            run = state["runs"][run_id]
            lines.append(
                f"{run_id} | status={run['status']} | mode={run['mode']} | "
                f"preset={run['preset_id']} | comments={run.get('comment_count', 0)}"
            )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage reproducible FlowArchitect test campaigns."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    template_p = sub.add_parser("template", help="Write an example campaign manifest")
    template_p.add_argument("--out", required=True, help="Where to write the template YAML")

    init_p = sub.add_parser("init", help="Create campaign directory from a manifest")
    init_p.add_argument("--manifest", required=True, help="Path to campaign manifest YAML")
    init_p.add_argument("--campaign-id", help="Override campaign id from manifest")
    init_p.add_argument("--force", action="store_true", help="Recreate campaign directory if it exists")

    sync_p = sub.add_parser("sync", help="Add missing runs from a manifest into an existing campaign")
    sync_p.add_argument("--campaign", required=True, help="Campaign id or path")
    sync_p.add_argument("--manifest", required=True, help="Path to campaign manifest YAML")

    run_p = sub.add_parser("run", help="Execute queued runs sequentially")
    run_p.add_argument("--campaign", required=True, help="Campaign id or path")
    run_p.add_argument("--limit", type=int, help="Maximum number of runs to execute")
    run_p.add_argument("--run-id", help="Run only one exact run_id")
    run_p.add_argument("--case", help="Run only a specific case_id")
    run_p.add_argument(
        "--include-statuses",
        default="queued",
        help="Comma-separated statuses to pick from (default: queued)",
    )
    run_p.add_argument("--python", help="Python executable for nested run_nl_test.py calls")
    run_p.add_argument(
        "--stop-on-statuses",
        help="Comma-separated statuses that should pause campaign execution",
    )

    materialize_p = sub.add_parser(
        "materialize",
        help="Import a saved run nifi.json into NiFi and keep it on canvas for manual testing",
    )
    materialize_p.add_argument("--campaign", required=True, help="Campaign id or path")
    materialize_p.add_argument("--run-id", required=True, help="Target run id")
    materialize_p.add_argument(
        "--replace-existing",
        action="store_true",
        help="Replace an existing root-level process group with the same name before import",
    )

    cleanup_p = sub.add_parser(
        "cleanup-nifi",
        help="Delete the materialized NiFi process group previously created for a run",
    )
    cleanup_p.add_argument("--campaign", required=True, help="Campaign id or path")
    cleanup_p.add_argument("--run-id", required=True, help="Target run id")

    status_p = sub.add_parser("status", help="Show current campaign summary")
    status_p.add_argument("--campaign", required=True, help="Campaign id or path")
    status_p.add_argument("--json", action="store_true", dest="as_json", help="Print raw campaign.json")
    status_p.add_argument("--verbose", action="store_true", help="Show every run")

    note_p = sub.add_parser("note", help="Append a campaign or run note")
    note_p.add_argument("--campaign", required=True, help="Campaign id or path")
    note_p.add_argument("--author", required=True, help="Author name for the note")
    note_p.add_argument("--kind", required=True, help="Note kind, e.g. operator_comment")
    note_p.add_argument("--text", required=True, help="Note text")
    note_p.add_argument("--run-id", help="Attach note to a specific run")
    note_p.add_argument("--status", help="Optionally set run status together with the note")

    set_status_p = sub.add_parser("set-status", help="Manually update a run status")
    set_status_p.add_argument("--campaign", required=True, help="Campaign id or path")
    set_status_p.add_argument("--run-id", required=True, help="Target run id")
    set_status_p.add_argument("--status", required=True, choices=sorted(STATUS_VALUES))
    set_status_p.add_argument("--author", help="Author for the accompanying note")
    set_status_p.add_argument("--note", help="Optional explanatory note")

    return parser


def cli(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "template":
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(TEMPLATE_MANIFEST, encoding="utf-8")
        print(out_path.resolve())
        return 0

    if args.command == "init":
        campaign_dir = initialize_campaign(
            manifest_path=Path(args.manifest),
            campaign_id=args.campaign_id,
            force=args.force,
        )
        print(campaign_dir)
        return 0

    if args.command == "sync":
        campaign_dir = resolve_campaign_dir(args.campaign)
        result = sync_campaign_with_manifest(campaign_dir, Path(args.manifest))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.command == "run":
        campaign_dir = resolve_campaign_dir(args.campaign)
        include_statuses = [part.strip() for part in args.include_statuses.split(",") if part.strip()]
        for status in include_statuses:
            if status not in STATUS_VALUES:
                raise ValueError(f"Unknown include status: {status}")
        stop_on_statuses = None
        if args.stop_on_statuses:
            stop_on_statuses = [part.strip() for part in args.stop_on_statuses.split(",") if part.strip()]
        result = execute_campaign_runs(
            campaign_dir=campaign_dir,
            limit=args.limit,
            include_statuses=include_statuses,
            run_id=args.run_id,
            case_id=args.case,
            python_executable=args.python,
            stop_on_statuses=stop_on_statuses,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.command == "materialize":
        campaign_dir = resolve_campaign_dir(args.campaign)
        result = materialize_run_in_nifi(
            campaign_dir=campaign_dir,
            run_id=args.run_id,
            replace_existing=args.replace_existing,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.command == "cleanup-nifi":
        campaign_dir = resolve_campaign_dir(args.campaign)
        result = cleanup_materialized_run(campaign_dir=campaign_dir, run_id=args.run_id)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.command == "status":
        campaign_dir = resolve_campaign_dir(args.campaign)
        state = load_state(campaign_dir)
        if args.as_json:
            print(json.dumps(state, indent=2, ensure_ascii=False))
        else:
            print(format_status_text(campaign_dir, state, verbose=args.verbose))
        return 0

    if args.command == "note":
        campaign_dir = resolve_campaign_dir(args.campaign)
        state = load_state(campaign_dir)
        append_note(
            campaign_dir=campaign_dir,
            state=state,
            author=args.author,
            kind=args.kind,
            text=args.text,
            run_id=args.run_id,
            status=args.status,
        )
        print("ok")
        return 0

    if args.command == "set-status":
        campaign_dir = resolve_campaign_dir(args.campaign)
        run = set_run_status(
            campaign_dir=campaign_dir,
            run_id=args.run_id,
            status=args.status,
            author=args.author,
            note=args.note,
        )
        print(json.dumps(summary_row(run), indent=2, ensure_ascii=False))
        return 0

    parser.error("Unknown command")
    return 2
