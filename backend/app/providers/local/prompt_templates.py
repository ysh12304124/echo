from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path


_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "prompts"
_PLACEHOLDER_PATTERN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


class PromptTemplateError(ValueError):
    pass


@lru_cache(maxsize=32)
def _load_template(name: str) -> str:
    path = _TEMPLATE_DIR / name
    if not path.is_file():
        raise PromptTemplateError(f"prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


def render_prompt_template(name: str, **values: object) -> str:
    template = _load_template(name)
    missing: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            missing.add(key)
            return match.group(0)
        value = values[key]
        return "" if value is None else str(value)

    rendered = _PLACEHOLDER_PATTERN.sub(replace, template)
    if missing:
        raise PromptTemplateError(
            f"missing prompt template values for {name}: {', '.join(sorted(missing))}"
        )
    return rendered
