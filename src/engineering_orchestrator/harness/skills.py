from __future__ import annotations

from pathlib import Path
from typing import Any


class SkillsService:
    def __init__(self, roots: list[str | Path] | None = None):
        self.roots = [Path(root) for root in (roots or ["skills", "config/skills"])]

    def list_instructions(self, base_dir: str | Path | None = None) -> list[dict[str, Any]]:
        base = Path(base_dir or ".").resolve()
        instructions: list[dict[str, Any]] = []
        for root in self.roots:
            path = root if root.is_absolute() else base / root
            if not path.exists():
                continue
            for skill_path in sorted(path.glob("*/SKILL.md")):
                instructions.append(
                    {
                        "id": skill_path.parent.name,
                        "path": str(skill_path),
                        "content": skill_path.read_text(encoding="utf-8"),
                    }
                )
        return instructions
