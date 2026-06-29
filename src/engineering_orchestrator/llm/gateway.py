from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from engineering_orchestrator.llm.types import ModelDecision


@dataclass(frozen=True)
class LLMGatewayResult:
    text: str
    prompt_chars: int
    status: str = "succeeded"


class LLMGateway:
    """Single dispatch point for future provider calls.

    The current MVP keeps real Codex/Responses calls in their existing adapters,
    but the orchestrator records model decisions through this boundary and new
    LLM operations should call through this gateway.
    """

    def call(self, decision: ModelDecision, prompt: str, provider: Callable[[str, ModelDecision], str] | None = None) -> LLMGatewayResult:
        if decision.runtime in {"mock", "deterministic"}:
            return LLMGatewayResult(text="", prompt_chars=len(prompt), status="skipped")
        if provider is None:
            raise RuntimeError(f"No provider configured for runtime `{decision.runtime}`.")
        return LLMGatewayResult(text=provider(prompt, decision), prompt_chars=len(prompt))
