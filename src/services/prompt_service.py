from __future__ import annotations

from pathlib import Path
from typing import Any


class PromptService:
    """
    Читает промпты из config/prompts и форматирует их через str.format(**context).
    """

    def __init__(self, prompts_dir: str | Path | None = None):
        # src/services/prompt_service.py -> src -> project_root
        default_dir = Path(__file__).resolve().parents[2] / "config" / "prompts"
        self.prompts_dir = Path(prompts_dir) if prompts_dir is not None else default_dir

    def get_prompt(self, filename: str, context: dict[str, Any] | None = None) -> str:
        context = context or {}
        path = self.prompts_dir / filename
        text = path.read_text(encoding="utf-8")
        # Use explicit key substitution instead of str.format() so that JSON
        # braces in the prompt template (e.g. {"flow": ...}) are never mistaken
        # for format placeholders.
        for key, value in context.items():
            text = text.replace(f"{{{key}}}", str(value))
        return text