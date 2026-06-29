from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached_prompt_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    source: str = "unknown"
    is_estimated: bool = False


_NUMBER = r"(?P<value>\d[\d,\s]*)"
_CODEX_TOTAL_PATTERNS = [
    re.compile(r"(?im)^\s*tokens\s+used\s*$\s*^\s*(?P<value>\d[\d,\s]*)\s*$"),
    re.compile(r"(?im)^\s*tokens\s+used\s*[:=]\s*(?P<value>\d[\d,\s]*)\s*$"),
]
_FIELD_PATTERNS = {
    "prompt_tokens": [
        re.compile(rf"(?im)^\s*(?:input|prompt)\s+tokens?\s*[:=]\s*{_NUMBER}"),
        re.compile(rf'(?im)"(?:input|prompt)_tokens"\s*:\s*{_NUMBER}'),
    ],
    "completion_tokens": [
        re.compile(rf"(?im)^\s*(?:output|completion)\s+tokens?\s*[:=]\s*{_NUMBER}"),
        re.compile(rf'(?im)"(?:output|completion)_tokens"\s*:\s*{_NUMBER}'),
    ],
    "cached_prompt_tokens": [
        re.compile(rf"(?im)\bcached(?:\s+(?:input|prompt))?\s+tokens?\s*[:=]\s*{_NUMBER}"),
        re.compile(rf'(?im)"cached_tokens"\s*:\s*{_NUMBER}'),
        re.compile(rf'(?im)"cached_(?:input|prompt)_tokens"\s*:\s*{_NUMBER}'),
    ],
    "reasoning_tokens": [
        re.compile(rf"(?im)^\s*reasoning\s+tokens?\s*[:=]\s*{_NUMBER}"),
        re.compile(rf'(?im)"reasoning_tokens"\s*:\s*{_NUMBER}'),
    ],
    "total_tokens": [
        re.compile(rf"(?im)^\s*total\s+tokens?\s*[:=]\s*{_NUMBER}"),
        re.compile(rf'(?im)"total_tokens"\s*:\s*{_NUMBER}'),
    ],
}


def parse_codex_cli_token_usage(stdout: str = "", stderr: str = "") -> TokenUsage | None:
    text = "\n".join(part for part in (stdout, stderr) if part)
    if not text:
        return None

    fields = {name: _last_number(text, patterns) for name, patterns in _FIELD_PATTERNS.items()}
    has_breakdown = any(
        fields[name] is not None
        for name in ("prompt_tokens", "completion_tokens", "cached_prompt_tokens", "reasoning_tokens")
    )
    if has_breakdown:
        total = fields["total_tokens"]
        if total is None:
            prompt = fields["prompt_tokens"] or 0
            completion = fields["completion_tokens"] or 0
            total = prompt + completion if fields["prompt_tokens"] is not None or fields["completion_tokens"] is not None else None
        return TokenUsage(
            prompt_tokens=fields["prompt_tokens"],
            completion_tokens=fields["completion_tokens"],
            cached_prompt_tokens=fields["cached_prompt_tokens"],
            reasoning_tokens=fields["reasoning_tokens"],
            total_tokens=total,
            source="codex_cli_reported_breakdown",
            is_estimated=False,
        )

    total = _last_number(text, _CODEX_TOTAL_PATTERNS)
    if total is not None:
        return TokenUsage(
            total_tokens=total,
            source="codex_cli_reported_total",
            is_estimated=False,
        )
    return None


def estimate_token_usage(prompt_chars: int, completion_chars: int) -> TokenUsage:
    prompt_tokens = _estimated_tokens_from_chars(prompt_chars)
    completion_tokens = _estimated_tokens_from_chars(completion_chars)
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        source="char_estimate",
        is_estimated=True,
    )


def _estimated_tokens_from_chars(chars: int) -> int:
    if chars <= 0:
        return 0
    return max(1, (chars + 3) // 4)


def _last_number(text: str, patterns: list[re.Pattern[str]]) -> int | None:
    value = None
    for pattern in patterns:
        for match in pattern.finditer(text):
            value = _parse_number(match.group("value"))
    return value


def _parse_number(value: str) -> int:
    return int(re.sub(r"[,\s]", "", value))
