from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from engineering_orchestrator.services.project_registry import ProjectRegistry


class ToolHealthService:
    def __init__(self, projects: ProjectRegistry, codex_bin: str, worktrees_root: str | Path, runtime_root: str | Path):
        self.projects = projects
        self.codex_bin = codex_bin
        self.worktrees_root = Path(worktrees_root)
        self.runtime_root = Path(runtime_root)

    def global_report(self) -> dict[str, Any]:
        items = {
            "git": self._available("git"),
            "codex_cli": self._available(self.codex_bin),
            "worktree_base_writable": self._writable(self.worktrees_root),
            "runtime_base_writable": self._writable(self.runtime_root),
        }
        mode = "ok" if all(items.values()) else "degraded"
        return {"mode": mode, "items": items}

    def task_report(self, project_id: str | None = None) -> dict[str, Any]:
        project = self.projects.get(project_id or "") or {}
        project_path = Path(str(project.get("path") or ".")) if project else None
        commands = [str(command) for command in project.get("test_commands", [])]
        tools = [str(tool) for tool in project.get("tools", [])]
        items = {
            **self.global_report()["items"],
            "project_path_exists": bool(project_path and project_path.exists()),
            "validators_configured": bool(commands),
        }
        mcp_tools = [tool for tool in tools if "mcp" in tool.lower()]
        unavailable_mcp = mcp_tools
        manual_review_required = str(project.get("validation_profile")) == "1c" and not commands
        mode = "degraded_no_mcp" if unavailable_mcp else ("manual_validation" if manual_review_required else "ok")
        return {
            "mode": mode,
            "project_id": project.get("id"),
            "manual_review_required": manual_review_required,
            "items": items,
            "required_tools": tools,
            "unavailable_mcp": unavailable_mcp,
            "validation_profile": project.get("validation_profile", "generic"),
            "test_commands": commands,
        }

    def markdown(self, report: dict[str, Any]) -> str:
        item_lines = [f"- {key}: `{'available' if value else 'unavailable'}`" for key, value in report.get("items", {}).items()]
        unavailable = report.get("unavailable_mcp") or []
        return f"""# Tool health

{chr(10).join(item_lines) if item_lines else "- No checks recorded."}

Mode: `{report.get("mode", "unknown")}`
Manual review required: `{'yes' if report.get("manual_review_required") else 'no'}`

## Unavailable MCP

{chr(10).join(f"- {item}" for item in unavailable) if unavailable else "- None."}
"""

    def _available(self, command: str) -> bool:
        return bool(shutil.which(command))

    def _writable(self, path: Path) -> bool:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".tasker-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return True
        except OSError:
            return False
