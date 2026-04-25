"""
CLI: replay a saved raw LLM response through the PIM parser and NiFiAdapter.
No Gemini API call, no NiFi connection required.

The "LLM response" is the raw text that Gemini would return — either a bare JSON
string or JSON wrapped in ```json ... ``` markdown fences.

Usage:
    python scripts/run_llm_fixture.py --llm-response <file.json> [--out <result.json>]

Save a real LLM response for replay:
    The easiest way is to add a print() to _call_gemini() in test_e2e_llm_to_nifi.py
    and save the raw_json variable to a file, then pass it here.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.nifi_adapter import NiFiAdapter
from src.domain.pim_model import Flow


def parse_pim(raw_text: str) -> Flow:
    """Mirror of Orchestrator._parse_json_to_flow — strip fences, validate."""
    raw = raw_text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    if m:
        raw = m.group(1).strip()
    data = json.loads(raw)
    return Flow.model_validate(data)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay saved LLM response: parse PIM → NiFiAdapter"
    )
    parser.add_argument("--llm-response", required=True, metavar="FILE",
                        help="File containing the raw LLM response text (JSON or fenced)")
    parser.add_argument("--out", metavar="FILE",
                        help="Write NiFi JSON to this file (default: stdout)")
    args = parser.parse_args()

    llm_path = Path(args.llm_response)
    if not llm_path.exists():
        print(f"ERROR: File not found: {llm_path}", file=sys.stderr)
        sys.exit(1)

    raw_text = llm_path.read_text(encoding="utf-8")
    print(f"[run_llm_fixture] Parsing LLM response from: {llm_path}", file=sys.stderr)
    print(f"[run_llm_fixture] Raw preview: {raw_text[:200]}{'...' if len(raw_text) > 200 else ''}",
          file=sys.stderr)

    try:
        pim = parse_pim(raw_text)
    except Exception as e:
        print(f"ERROR: Failed to parse PIM: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[run_llm_fixture] Flow: '{pim.flow.name}' | "
          f"sources={len(pim.sources)} processing={len(pim.processing_elements)} sinks={len(pim.sinks)}",
          file=sys.stderr)

    adapter = NiFiAdapter()
    result = adapter.convert(pim)

    processors = result.get("flowContents", {}).get("processors", [])
    connections = result.get("flowContents", {}).get("connections", [])
    print(f"[run_llm_fixture] Generated: {len(processors)} processor(s), {len(connections)} connection(s)",
          file=sys.stderr)
    for p in processors:
        print(f"  - {p.get('name')} ({p.get('type', '').split('.')[-1]})", file=sys.stderr)

    output = json.dumps(result, indent=2, ensure_ascii=False)

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(output, encoding="utf-8")
        print(f"[run_llm_fixture] Written to: {out_path}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
