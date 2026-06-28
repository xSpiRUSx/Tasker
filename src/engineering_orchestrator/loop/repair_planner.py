from __future__ import annotations

import json
from typing import Any


class RepairPlanner:
    def build_prompt(self, findings: list[dict[str, Any]], validation_summary: str, diff_patch: str) -> str:
        return f"""# Repair prompt

Validation or evaluation did not pass. Repair only the approved task scope and preserve existing approval gates.

## Findings

```json
{json.dumps(findings, ensure_ascii=False, indent=2)}
```

## Validation summary

{validation_summary}

## Current diff

```diff
{diff_patch}
```
"""
