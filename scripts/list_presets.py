"""
CLI: list all configured LLM presets from config/settings.json.

Usage:
    python scripts/list_presets.py
    python scripts/list_presets.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.managers.app_paths import settings_path

_BUILTIN_PRESETS = [
    {"id": 1, "name": "OpenRouter DeepSeek V4 Pro", "default_model": "deepseek/deepseek-v4-pro",
     "url": "https://openrouter.ai/api/v1/chat/completions", "key": ""},
    {"id": 2, "name": "OpenRouter Qwen 3.6 Plus", "default_model": "qwen/qwen3.6-plus",
     "url": "https://openrouter.ai/api/v1/chat/completions", "key": ""},
    {"id": 3, "name": "OpenRouter Claude Sonnet 4.6", "default_model": "anthropic/claude-sonnet-4.6",
     "url": "https://openrouter.ai/api/v1/chat/completions", "key": ""},
    {"id": 4, "name": "OpenAI", "default_model": "gpt-4o-mini",
     "url": "https://api.openai.com/v1/chat/completions", "key": ""},
    {"id": 5, "name": "Google Gemini", "default_model": "gemini-2.5-flash",
     "url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent", "key": ""},
]


def _load_presets() -> dict[str, dict]:
    """Return {str(id): preset_dict} from config/settings.json."""
    path = settings_path()
    if not path.exists():
        print(f"ERROR: {path} not found. Run the app at least once to create it.", file=sys.stderr)
        sys.exit(1)
    data = json.loads(path.read_text(encoding="utf-8"))

    result: dict[str, dict] = {}

    # Built-in presets, may have overrides
    overrides = data.get("API_PRESETS_BUILTIN_OVERRIDES", {}) or {}
    for b in _BUILTIN_PRESETS:
        merged = dict(b)
        merged.update(overrides.get(str(b["id"]), {}) or {})
        result[str(b["id"])] = merged

    # Custom presets
    for p in data.get("API_PRESETS_CUSTOM", []) or []:
        if isinstance(p, dict) and "id" in p:
            result[str(p["id"])] = p

    return result


def _mask_key(key: str) -> str:
    if not key:
        return "(empty)"
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "..." + key[-4:]


def main() -> None:
    parser = argparse.ArgumentParser(description="List configured LLM presets.")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="Output as JSON instead of table")
    args = parser.parse_args()

    presets = _load_presets()

    if args.as_json:
        safe = {
            pid: {k: v for k, v in p.items() if k not in ("key", "reserve_keys")}
            for pid, p in presets.items()
        }
        print(json.dumps(safe, indent=2, ensure_ascii=False))
        return

    if not presets:
        print("No presets found in config/settings.json")
        return

    # Table header
    col_id    = 4
    col_name  = 26
    col_model = 30
    col_url   = 40
    col_key   = 16

    header = (
        f"{'ID':<{col_id}}  "
        f"{'Name':<{col_name}}  "
        f"{'Default model':<{col_model}}  "
        f"{'URL':<{col_url}}  "
        f"{'Key (masked)':<{col_key}}"
    )
    sep = "-" * len(header)

    print()
    print(header)
    print(sep)

    for pid in sorted(presets, key=lambda x: int(x)):
        p = presets[pid]
        name  = (p.get("name") or "")[:col_name]
        model = (p.get("default_model") or "")[:col_model]
        url   = (p.get("url") or "")[:col_url]
        key   = _mask_key(p.get("key") or "")

        print(
            f"{pid:<{col_id}}  "
            f"{name:<{col_name}}  "
            f"{model:<{col_model}}  "
            f"{url:<{col_url}}  "
            f"{key:<{col_key}}"
        )

    print()
    print(f"Total: {len(presets)} preset(s)")
    print()
    print("Use --preset <ID or name substring> with run_nl_test.py")


if __name__ == "__main__":
    main()
