from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PackageResult:
    status: str
    source_paths: list[str] = field(default_factory=list)
    output_paths: list[str] = field(default_factory=list)
    manual_build_required: bool = False
    logs: str = ""


class ExternalProcessingPackageService:
    def package(self, task_id: str, project: dict[str, Any] | None, worktree_path: str | Path | None, changed_files: list[str]) -> PackageResult:
        config = dict((project or {}).get("external_processing") or {})
        source_root = str(config.get("source_root") or "src/epf").replace("\\", "/").rstrip("/")
        source_paths = sorted({file_name for file_name in changed_files if file_name.replace("\\", "/").startswith(source_root + "/")})
        if not source_paths:
            return PackageResult(status="skipped", source_paths=[], manual_build_required=False)

        build_tool = config.get("build_tool")
        command = config.get("package_command")
        if not build_tool or str(build_tool).lower() == "none" or not command:
            return PackageResult(status="manual_build_required", source_paths=source_paths, manual_build_required=True)

        if not worktree_path:
            return PackageResult(status="failed", source_paths=source_paths, manual_build_required=False, logs="No worktree is attached.")

        command_text = str(command).format(task_id=task_id)
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command_text],
            cwd=Path(worktree_path),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        logs = (completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")
        status = "passed" if completed.returncode == 0 else "failed"
        output_dir = str(config.get("output_dir") or f"data/outputs/{task_id}").format(task_id=task_id)
        outputs = self._collect_outputs(Path(worktree_path) / output_dir) if status == "passed" else []
        return PackageResult(status=status, source_paths=source_paths, output_paths=outputs, manual_build_required=False, logs=logs)

    def markdown(self, result: PackageResult) -> str:
        lines = [
            "# External processing package",
            "",
            f"Status: `{result.status}`",
            f"Manual build required: `{'yes' if result.manual_build_required else 'no'}`",
            "",
            "## Source files",
            "",
            *[f"- `{path}`" for path in result.source_paths],
        ]
        if not result.source_paths:
            lines.append("- None.")
        lines.extend(["", "## Output files", ""])
        lines.extend([f"- `{path}`" for path in result.output_paths] or ["- None."])
        if result.manual_build_required:
            lines.extend(
                [
                    "",
                    "## Next steps",
                    "",
                    "Build/load the external processing manually in 1C Designer or configure `package_command`.",
                ]
            )
        if result.logs:
            lines.extend(["", "## Logs", "", "```text", result.logs.strip(), "```"])
        return "\n".join(lines).rstrip() + "\n"

    def _collect_outputs(self, output_dir: Path) -> list[str]:
        if not output_dir.exists():
            return []
        return sorted(str(path.relative_to(output_dir.parent)).replace("\\", "/") for path in output_dir.rglob("*") if path.is_file())
