from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class ValidationCommandResult(BaseModel):
    command: str
    status: Literal["passed", "failed", "timed_out"]
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0


class ValidationResult(BaseModel):
    status: Literal["passed", "failed", "skipped"]
    summary: str
    commands: list[ValidationCommandResult] = Field(default_factory=list)
    profile: str = "generic"
    manual_review_required: bool = False


class ValidationService:
    def __init__(self, timeout_seconds: int = 900):
        self.timeout_seconds = timeout_seconds

    def mock_report(self) -> str:
        return "Mock validation passed. No project test commands were executed."

    def run(
        self,
        commands: list[str],
        worktree_path: str | Path | None,
        validation_profile: str = "generic",
    ) -> ValidationResult:
        if not worktree_path:
            return ValidationResult(
                status="skipped",
                summary="No worktree is attached to this task.",
                profile=validation_profile,
            )

        cwd = Path(worktree_path)
        if not cwd.exists():
            return ValidationResult(
                status="failed",
                summary=f"Validation worktree does not exist: {cwd}",
                profile=validation_profile,
            )

        if not commands:
            if validation_profile == "1c":
                return ValidationResult(
                    status="skipped",
                    summary="No configured 1C validator; manual review is required.",
                    profile=validation_profile,
                    manual_review_required=True,
                )
            return ValidationResult(
                status="skipped",
                summary="Project has no configured test_commands.",
                profile=validation_profile,
            )

        results = [self._run_command(command, cwd) for command in commands]
        failed = [result for result in results if result.status != "passed"]
        if failed:
            return ValidationResult(
                status="failed",
                summary=f"{len(failed)} of {len(results)} validation command(s) failed.",
                commands=results,
                profile=validation_profile,
            )
        return ValidationResult(
            status="passed",
            summary=f"All {len(results)} validation command(s) passed.",
            commands=results,
            profile=validation_profile,
        )

    def markdown_report(self, result: ValidationResult) -> str:
        lines = [
            "# Validation",
            "",
            f"Status: `{result.status}`",
            f"Profile: `{result.profile}`",
            f"Manual review required: `{'yes' if result.manual_review_required else 'no'}`",
            "",
            result.summary,
            "",
            "## Commands",
            "",
        ]
        if not result.commands:
            lines.append("- None.")
            return "\n".join(lines).rstrip() + "\n"

        for index, command in enumerate(result.commands, start=1):
            lines.extend(
                [
                    f"### {index}. `{command.command}`",
                    "",
                    f"- Status: `{command.status}`",
                    f"- Exit code: `{command.returncode if command.returncode is not None else 'none'}`",
                    f"- Duration: `{command.duration_seconds:.2f}s`",
                    "",
                    "#### stdout",
                    "",
                    "```text",
                    command.stdout.strip() or "(empty)",
                    "```",
                    "",
                    "#### stderr",
                    "",
                    "```text",
                    command.stderr.strip() or "(empty)",
                    "```",
                    "",
                ]
            )
        return "\n".join(lines).rstrip() + "\n"

    def command_output_markdown(self, command: ValidationCommandResult) -> str:
        return f"""# Validation command output

Command: `{command.command}`
Status: `{command.status}`
Exit code: `{command.returncode if command.returncode is not None else 'none'}`
Duration: `{command.duration_seconds:.2f}s`

## stdout

```text
{command.stdout.strip() or "(empty)"}
```

## stderr

```text
{command.stderr.strip() or "(empty)"}
```
"""

    def _run_command(self, command: str, cwd: Path) -> ValidationCommandResult:
        import time

        started = time.monotonic()
        try:
            completed = subprocess.run(
                self._shell_command(command),
                cwd=cwd,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            duration = time.monotonic() - started
            return ValidationCommandResult(
                command=command,
                status="passed" if completed.returncode == 0 else "failed",
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_seconds=duration,
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - started
            return ValidationCommandResult(
                command=command,
                status="timed_out",
                returncode=None,
                stdout=_decode_timeout_output(exc.stdout),
                stderr=_decode_timeout_output(exc.stderr),
                duration_seconds=duration,
            )

    def _shell_command(self, command: str) -> list[str]:
        if os.name == "nt":
            return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
        return ["/bin/sh", "-lc", command]


def _decode_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
