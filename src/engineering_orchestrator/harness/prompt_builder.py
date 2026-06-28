from __future__ import annotations

import json

from engineering_orchestrator.harness.working_memory import WorkingMemory


class PromptBuilder:
    def render_planner_prompt(self, memory: WorkingMemory) -> str:
        return self._render(memory, "Produce spec/todo/test plan artifacts. Do not modify files.")

    def render_executor_prompt(self, memory: WorkingMemory, plan_text: str) -> str:
        return self._render(memory, f"Implement the approved plan.\n\n# Approved plan\n\n{plan_text}")

    def render_reviewer_prompt(self, memory: WorkingMemory, diff_summary: str) -> str:
        return self._render(memory, f"Review the completed work and recommend approve/request changes/reject.\n\n# Diff summary\n\n{diff_summary}")

    def render_memory_markdown(self, memory: WorkingMemory) -> str:
        return self._render(memory, "This artifact captures the working memory passed to harness agents.")

    def _render(self, memory: WorkingMemory, output_requirements: str) -> str:
        return f"""# Role

You are Tasker's engineering harness. Preserve approval gates and make decisions from stored context.

# User task

{memory.user_prompt}

# Route decision

```json
{json.dumps(memory.route_decision or {}, ensure_ascii=False, indent=2)}
```

# Project profile

```json
{json.dumps(memory.project_profile or {}, ensure_ascii=False, indent=2)}
```

# Workflow policy

```json
{json.dumps(memory.workflow_policy or {}, ensure_ascii=False, indent=2)}
```

# Current artifacts

```json
{json.dumps(memory.current_artifacts, ensure_ascii=False, indent=2)}
```

# Procedural instructions

{self._instruction_list(memory)}

# Tool policy

```json
{json.dumps(memory.tool_policy or {}, ensure_ascii=False, indent=2)}
```

# Approval gates

{self._bullet_list(memory.approval_gates)}

# Stop conditions

```json
{json.dumps(memory.stop_conditions or {}, ensure_ascii=False, indent=2)}
```

# Output requirements

{output_requirements}
"""

    def _instruction_list(self, memory: WorkingMemory) -> str:
        if not memory.procedural_instructions:
            return "- None."
        return "\n".join(
            f"- `{item.get('id')}` from `{item.get('path')}`" for item in memory.procedural_instructions
        )

    def _bullet_list(self, values: list[str]) -> str:
        if not values:
            return "- None."
        return "\n".join(f"- {value}" for value in values)
