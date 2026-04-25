"""
CLI: import NiFi JSON into a live NiFi instance, capture all errors, save report.
Always cleans up (deletes the created process-group) after capture.

Credentials are read from environment variables — never passed as arguments:
    NIFI_URL   — e.g. https://localhost:8443  (default: https://localhost:8443)
    NIFI_USER  — NiFi username
    NIFI_PASS  — NiFi password

Usage:
    python scripts/import_and_report.py <nifi_flow.json> [--report <errors.json>]

Examples:
    python scripts/import_and_report.py result.json
    python scripts/import_and_report.py result.json --report errors.json

Output report structure:
    {
      "import_ok": bool,
      "import_error": str | null,
      "pg_id": str | null,
      "processors": [{"name": ..., "type": ..., "errors": [...]}],
      "processor_count": int,
      "error_count": int,
      "summary": str
    }
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.services.nifi_client import NiFiClient


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
        description="Import NiFi JSON → capture validation errors → cleanup"
    )
    parser.add_argument("nifi_json", help="Path to NiFi flow JSON (NiFiAdapter output)")
    parser.add_argument("--report", metavar="FILE",
                        help="Save error report to this JSON file (default: stdout)")
    args = parser.parse_args()

    flow_path = Path(args.nifi_json)
    if not flow_path.exists():
        print(f"ERROR: File not found: {flow_path}", file=sys.stderr)
        sys.exit(1)

    flow_json = json.loads(flow_path.read_text(encoding="utf-8"))
    client = _nifi_client()

    # Check connectivity first
    ok, msg = client.test_connection()
    if not ok:
        print(f"ERROR: Cannot connect to NiFi: {msg}", file=sys.stderr)
        sys.exit(1)
    print(f"[import_and_report] Connected: {msg}", file=sys.stderr)

    # Import
    print(f"[import_and_report] Importing flow...", file=sys.stderr)
    import_ok, import_result = client.import_flow(flow_json)

    report: dict = {
        "import_ok": import_ok,
        "import_error": None,
        "pg_id": None,
        "processors": [],
        "processor_count": 0,
        "error_count": 0,
        "summary": "",
    }

    if not import_ok:
        report["import_error"] = import_result
        report["summary"] = f"IMPORT FAILED: {import_result}"
        print(f"[import_and_report] Import failed: {import_result}", file=sys.stderr)
    else:
        pg_id = import_result
        report["pg_id"] = pg_id
        print(f"[import_and_report] Created process-group: {pg_id}", file=sys.stderr)

        # Collect validation errors
        # Enable controller services (NiFi imports them as DISABLED by default)
        n_enabled = client.enable_controller_services(pg_id)
        if n_enabled:
            print(f"[import_and_report] Enabled {n_enabled} controller service(s).", file=sys.stderr)

        print(f"[import_and_report] Collecting validation errors...", file=sys.stderr)
        errors = client.get_validation_errors(pg_id)
        report["processors"] = errors
        report["processor_count"] = len(errors)
        report["error_count"] = sum(len(e["errors"]) for e in errors)

        if errors:
            report["summary"] = (
                f"{report['error_count']} validation error(s) across "
                f"{report['processor_count']} processor(s)"
            )
            print(f"[import_and_report] {report['summary']}", file=sys.stderr)
            for proc in errors:
                print(f"  Processor: {proc['name']} ({proc['type'].split('.')[-1]})",
                      file=sys.stderr)
                for err in proc["errors"]:
                    print(f"    ! {err}", file=sys.stderr)
        else:
            report["summary"] = "No validation errors — flow imported cleanly."
            print(f"[import_and_report] {report['summary']}", file=sys.stderr)

        # Cleanup
        print(f"[import_and_report] Cleaning up PG {pg_id}...", file=sys.stderr)
        try:
            client.delete_pg(pg_id)
            print(f"[import_and_report] Deleted.", file=sys.stderr)
        except Exception as e:
            print(f"[import_and_report] WARNING: cleanup failed: {e}", file=sys.stderr)

    output = json.dumps(report, indent=2, ensure_ascii=False)

    if args.report:
        out_path = Path(args.report)
        out_path.write_text(output, encoding="utf-8")
        print(f"[import_and_report] Report written to: {out_path}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
