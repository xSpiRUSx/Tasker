from __future__ import annotations

import re

from task_router.adaptive.config import NormalizationConfig


PUNCTUATION_RE = re.compile(r"[^\w\s-]+", re.UNICODE)
SPACES_RE = re.compile(r"\s+")


def normalize_message(message: str, config: NormalizationConfig | None = None) -> str:
    options = config or NormalizationConfig()
    text = message.strip()
    if options.lowercase:
        text = text.lower()
    if options.replace_yo:
        text = text.replace("ё", "е")
    if options.strip_punctuation:
        text = PUNCTUATION_RE.sub(" ", text)
    if options.collapse_spaces:
        text = SPACES_RE.sub(" ", text).strip()
    return text
