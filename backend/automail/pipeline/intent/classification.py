"""Intent classification prompt."""

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_CLASSIFY_SYSTEM_PROMPT = (_PROMPTS_DIR / "classification_system_prompt.md").read_text(encoding="utf-8").strip()
