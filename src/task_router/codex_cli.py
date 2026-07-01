from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from task_router.llm import build_router_prompt
from task_router.models import RouterConfig, UserTaskAnalysis


def analyze_with_codex_cli(text: str, config: RouterConfig) -> UserTaskAnalysis:
    schema = _strict_json_schema(UserTaskAnalysis.model_json_schema())

    prompt = f"""
{build_router_prompt(config)}

User task:
{text}
""".strip()

    codex_bin = _resolve_codex_bin(os.getenv("TASK_ROUTER_CODEX_BIN", "codex"))
    model = os.getenv("TASK_ROUTER_CODEX_MODEL")
    timeout_seconds = int(os.getenv("TASK_ROUTER_CODEX_TIMEOUT_SECONDS", "120"))

    with tempfile.TemporaryDirectory(prefix="task-router-codex-") as tmp:
        schema_path = Path(tmp) / "analysis.schema.json"
        schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")

        command = [codex_bin, "exec", "-", "--output-schema", str(schema_path), "--skip-git-repo-check"]
        if model:
            command.extend(["--model", model])

        try:
            completed = subprocess.run(
                _windows_command(command),
                check=False,
                capture_output=True,
                input=prompt,
                text=True,
                encoding="utf-8",
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Codex CLI classification timed out after {timeout_seconds} seconds.") from exc

    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        raise RuntimeError(
            "Codex CLI classification failed. Run `codex login` first and retry."
            + (f"\n\nCodex stderr:\n{stderr}" if stderr else "")
        )

    payload = _extract_json_object(completed.stdout)
    return UserTaskAnalysis.model_validate(payload)


def _resolve_codex_bin(codex_bin: str) -> str:
    resolved = shutil.which(codex_bin)
    return resolved or codex_bin


def _windows_command(command: list[str]) -> list[str]:
    if os.name != "nt":
        return command

    suffix = Path(command[0]).suffix.lower()
    if suffix in {".cmd", ".bat"}:
        return ["cmd.exe", "/d", "/s", "/c", subprocess.list2cmdline(command)]
    return command


def _strict_json_schema(schema: dict) -> dict:
    def visit(node):
        if isinstance(node, dict):
            node.pop("default", None)
            properties = node.get("properties")
            if isinstance(properties, dict):
                node["required"] = list(properties.keys())
                node["additionalProperties"] = False
                for child in properties.values():
                    visit(child)
            for key in ("$defs", "definitions"):
                values = node.get(key)
                if isinstance(values, dict):
                    for child in values.values():
                        visit(child)
            for key in ("anyOf", "oneOf", "allOf"):
                values = node.get(key)
                if isinstance(values, list):
                    for child in values:
                        visit(child)
            if isinstance(node.get("items"), dict):
                visit(node["items"])
        elif isinstance(node, list):
            for item in node:
                visit(item)
        return node

    return visit(json.loads(json.dumps(schema)))


def _extract_json_object(text: str) -> dict:
    stripped = text.strip()
    if not stripped:
        raise RuntimeError("Codex CLI returned an empty response.")

    try:
        value = json.loads(stripped)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise RuntimeError(f"Codex CLI did not return a JSON object:\n{stripped}")

    value = json.loads(stripped[start : end + 1])
    if not isinstance(value, dict):
        raise RuntimeError("Codex CLI returned JSON, but it was not an object.")
    return value
