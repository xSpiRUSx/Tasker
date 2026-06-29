from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class AdaptiveConfidenceThresholds(BaseModel):
    accept_deterministic: float = 0.85
    call_cheap_classifier_below: float = 0.75
    ask_clarification_below: float = 0.60


class CheapClassifierConfig(BaseModel):
    enabled: bool = True
    operation: str = "adaptive_route_fallback"
    model_target: str = "cheap_classifier"
    max_prompt_chars: int = 12000
    include_recent_tasks: bool = True
    recent_tasks_limit: int = 20
    include_project_aliases: bool = True
    include_active_rules: bool = True
    include_code: bool = False
    include_artifacts: bool = False
    include_diffs: bool = False
    include_runtime_logs: bool = False


class LearningConfig(BaseModel):
    enabled: bool = True
    auto_promote: bool = False
    require_human_approval: bool = True
    create_eval_cases: bool = True
    min_confidence_for_suggestion: float = 0.80
    min_confidence_for_auto_promote: float = 0.92


class SafetyConfig(BaseModel):
    never_auto_promote_for: list[str] = Field(
        default_factory=lambda: [
            "config_change",
            "security_change",
            "role_change",
            "deployment_change",
            "migration",
            "high_risk_workflow",
        ]
    )
    disable_after_false_positives: int = 2


class NormalizationConfig(BaseModel):
    lowercase: bool = True
    replace_yo: bool = True
    collapse_spaces: bool = True
    strip_punctuation: bool = False


class AdaptiveRoutingConfig(BaseModel):
    enabled: bool = True
    deterministic_first: bool = True
    confidence_thresholds: AdaptiveConfidenceThresholds = Field(default_factory=AdaptiveConfidenceThresholds)
    cheap_classifier: CheapClassifierConfig = Field(default_factory=CheapClassifierConfig)
    learning: LearningConfig = Field(default_factory=LearningConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    normalization: NormalizationConfig = Field(default_factory=NormalizationConfig)


def load_adaptive_routing_config(path: str | Path | None) -> AdaptiveRoutingConfig:
    if path is None:
        return AdaptiveRoutingConfig()
    config_path = Path(path)
    if not config_path.exists():
        return AdaptiveRoutingConfig()
    data: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return AdaptiveRoutingConfig(**(data.get("adaptive_routing") or data))
