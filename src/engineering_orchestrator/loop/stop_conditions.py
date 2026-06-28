from __future__ import annotations

from pydantic import BaseModel


class LoopPolicy(BaseModel):
    max_iterations: int = 2
    max_changed_files: int = 12
    max_diff_lines: int = 1200
    repair_on_validation_failure: bool = True
    require_human_on_blocked_path: bool = True
    require_human_on_config_change: bool = True
