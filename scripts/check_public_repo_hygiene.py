from __future__ import annotations

import argparse
import fnmatch
import subprocess
from pathlib import Path


BLOCKED_PATTERNS = [
    ".env",
    ".env.*",
    "orchestrator.sqlite3",
    "data/runtime/**",
    "data/worktrees/**",
    "data/obsidian-tasks/**",
    "runtime/**",
    "worktrees/**",
    "obsidian-tasks/**",
    "node_modules/**",
    "web/node_modules/**",
    "web/dist/**",
    "dist/*.zip",
    "*.sqlite",
    "*.sqlite3",
    "*.db",
    "*.log",
]

ALLOW_PATTERNS = [
    ".env.example",
    ".env.*.example",
    "web/.env.example",
]

SECRET_HINTS = [
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
]


def normalize(path: Path | str) -> str:
    return str(path).replace("\\", "/").lstrip("./")


def matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def git_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files"],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def env_file_has_real_values(path: Path) -> bool:
    if not path.exists() or path.name.endswith(".example"):
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if not value or value.lower() in {"changeme", "example", "placeholder", "todo"}:
            continue
        if any(hint in key.lower() for hint in SECRET_HINTS):
            return True
    return False


def check(root: Path) -> list[str]:
    violations: list[str] = []
    for rel in git_files(root):
        if matches(rel, ALLOW_PATTERNS):
            continue
        if matches(rel, BLOCKED_PATTERNS):
            violations.append(f"tracked blocked file: {rel}")

    for env_path in root.glob(".env*"):
        rel = normalize(env_path.relative_to(root))
        if matches(rel, ALLOW_PATTERNS):
            continue
        if env_file_has_real_values(env_path):
            violations.append(f"real values detected in env file: {rel}")

    return sorted(set(violations))


def main() -> None:
    parser = argparse.ArgumentParser(description="Check that the public repo has no local runtime/private data.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    violations = check(root)
    if violations:
        print("Public repo hygiene check failed:")
        for violation in violations:
            print(f"- {violation}")
        raise SystemExit(1)
    print("Public repo hygiene check passed.")


if __name__ == "__main__":
    main()
