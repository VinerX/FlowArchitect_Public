"""
CLI: full debug pipeline — PIM → adapter → NiFi import → error report.
Combines run_adapter.py and import_and_report.py in one call.

Credentials read from env vars (NIFI_URL, NIFI_USER, NIFI_PASS).

Usage:
    python scripts/full_pipeline.py <pim_file> [--report <errors.json>] [--keep-nifi-json <file.json>]

Examples:
    python scripts/full_pipeline.py tests/fixtures/kafka_to_postgres.json
    python scripts/full_pipeline.py tests/fixtures/s3_to_hdfs.json --report errors.json
    python scripts/full_pipeline.py my_pim.yaml --keep-nifi-json result.json --report errors.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.nifi_adapter import NiFiAdapter
from src.domain.pim_model import Flow
from src.services.nifi_client import NiFiClient


def load_pim(path: Path) -> Flow:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        import yaml
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    return Flow.model_validate(data)


def _nifi_client() -> NiFiClient:
    url  = os.environ.get("NIFI_URL",  "https://localhost:8443")
    user = os.environ.get("NIFI_USER", "")
    pwd  = os.environ.get("NIFI_PASS", "")
    if not user or not pwd:
        print("ERROR: Set NIFI_USER and NIFI_PASS environment variables.", file=sys.stderr)
        sys.exit(1)
    return NiFiClient(url, user, pwd)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PIM → NiFiAdapter → NiFi import → error report (full debug loop)"
    )
    parser.add_argument("pim_file", help="Path to PIM file (.json or .yaml)")
    parser.add_argument("--report", metavar="FILE",
                        help="Save error report to this JSON file (default: stdout)")
    parser.add_argument("--keep-nifi-json", metavar="FILE",
                        help="Also save intermediate NiFi JSON to this file")
    args = parser.parse_args()

    pim_path = Path(args.pim_file)
    if not pim_path.exists():
        print(f"ERROR: File not found: {pim_path}", file=sys.stderr)
        sys.exit(1)

    # ── Step 1: Load PIM ──────────────────────────────────────────────────────
    print(f"[pipeline] Loading PIM: {pim_path}", file=sys.stderr)
    pim = load_pim(pim_path)
    print(f"[pipeline] Flow: '{pim.flow.name}' | "
          f"sources={len(pim.sources)} processing={len(pim.processing_elements)} sinks={len(pim.sinks)}",
          file=sys.stderr)

    # ── Step 2: Connect to NiFi + detect version ─────────────────────────────
    client = _nifi_client()
    ok, msg = client.test_connection()
    if not ok:
        print(f"ERROR: Cannot connect to NiFi: {msg}", file=sys.stderr)
        sys.exit(1)
    nifi_version = client.get_version()
    print(f"[pipeline] NiFi: {msg} (version={nifi_version})", file=sys.stderr)

    # ── Step 3: NiFiAdapter ───────────────────────────────────────────────────
    adapter = NiFiAdapter(nifi_version=nifi_version)
    nifi_json = adapter.convert(pim)
    processors = nifi_json.get("flowContents", {}).get("processors", [])
    connections = nifi_json.get("flowContents", {}).get("connections", [])
    print(f"[pipeline] Adapter: {len(processors)} processor(s), {len(connections)} connection(s)",
          file=sys.stderr)
    for p in processors:
        print(f"  - {p.get('name')} ({p.get('type', '').split('.')[-1]})", file=sys.stderr)

    if args.keep_nifi_json:
        kp = Path(args.keep_nifi_json)
        kp.write_text(json.dumps(nifi_json, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[pipeline] NiFi JSON saved to: {kp}", file=sys.stderr)

    # ── Step 4: NiFi import + error capture ───────────────────────────────────

    print(f"[pipeline] Importing...", file=sys.stderr)
    import_ok, import_result = client.import_flow(nifi_json)

    report: dict = {
        "pim_file": str(pim_path),
        "flow_name": pim.flow.name,
        "adapter_processors": [
            {"name": p.get("name"), "type": p.get("type", "").split(".")[-1]}
            for p in processors
        ],
        "import_ok": import_ok,
        "import_error": None,
        "pg_id": None,
        "validation_errors": [],
        "error_count": 0,
        "summary": "",
    }

    if not import_ok:
        report["import_error"] = import_result
        report["summary"] = f"IMPORT FAILED: {import_result}"
        print(f"[pipeline] {report['summary']}", file=sys.stderr)
    else:
        pg_id = import_result
        report["pg_id"] = pg_id
        print(f"[pipeline] Created PG: {pg_id}", file=sys.stderr)

        n_enabled = client.enable_controller_services(pg_id)
        if n_enabled:
            print(f"[pipeline] Enabled {n_enabled} controller service(s).", file=sys.stderr)

        errors = client.get_validation_errors(pg_id)
        report["validation_errors"] = errors
        report["error_count"] = sum(len(e["errors"]) for e in errors)

        if errors:
            report["summary"] = (
                f"{report['error_count']} validation error(s) across {len(errors)} processor(s)"
            )
            print(f"[pipeline] {report['summary']}", file=sys.stderr)
            for proc in errors:
                print(f"  Processor: {proc['name']} ({proc['type'].split('.')[-1]})",
                      file=sys.stderr)
                for err in proc["errors"]:
                    print(f"    ! {err}", file=sys.stderr)
        else:
            report["summary"] = "OK — no validation errors."
            print(f"[pipeline] {report['summary']}", file=sys.stderr)

        print(f"[pipeline] Cleanup...", file=sys.stderr)
        try:
            client.delete_pg(pg_id)
        except Exception as e:
            print(f"[pipeline] WARNING: cleanup failed: {e}", file=sys.stderr)

    output = json.dumps(report, indent=2, ensure_ascii=False)

    if args.report:
        out_path = Path(args.report)
        out_path.write_text(output, encoding="utf-8")
        print(f"[pipeline] Report written to: {out_path}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
