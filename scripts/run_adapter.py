"""
CLI: run NiFiAdapter against a PIM file (JSON or YAML). No tokens required.

Usage:
    python scripts/run_adapter.py <pim_file> [--out <output.json>]

Examples:
    python scripts/run_adapter.py tests/fixtures/kafka_to_postgres.json
    python scripts/run_adapter.py my_pim.yaml --out result.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.nifi_adapter import NiFiAdapter
from src.domain.pim_model import Flow


def load_pim(path: Path) -> Flow:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        import yaml
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    return Flow.model_validate(data)


def main() -> None:
    parser = argparse.ArgumentParser(description="PIM → NiFi JSON via NiFiAdapter")
    parser.add_argument("pim_file", help="Path to PIM file (.json or .yaml)")
    parser.add_argument("--out", metavar="FILE", help="Write NiFi JSON to this file (default: stdout)")
    args = parser.parse_args()

    pim_path = Path(args.pim_file)
    if not pim_path.exists():
        print(f"ERROR: File not found: {pim_path}", file=sys.stderr)
        sys.exit(1)

    print(f"[run_adapter] Loading PIM: {pim_path}", file=sys.stderr)
    pim = load_pim(pim_path)
    print(f"[run_adapter] Flow: '{pim.flow.name}' | "
          f"sources={len(pim.sources)} processing={len(pim.processing_elements)} sinks={len(pim.sinks)}",
          file=sys.stderr)

    adapter = NiFiAdapter()
    result = adapter.convert(pim)

    processors = result.get("flowContents", {}).get("processors", [])
    connections = result.get("flowContents", {}).get("connections", [])
    print(f"[run_adapter] Generated: {len(processors)} processor(s), {len(connections)} connection(s)",
          file=sys.stderr)
    for p in processors:
        print(f"  - {p.get('name')} ({p.get('type', '').split('.')[-1]})", file=sys.stderr)

    output = json.dumps(result, indent=2, ensure_ascii=False)

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(output, encoding="utf-8")
        print(f"[run_adapter] Written to: {out_path}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
