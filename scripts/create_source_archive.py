from __future__ import annotations

import argparse
import fnmatch
import zipfile
from pathlib import Path


INCLUDE_ROOTS = [
    "src",
    "tests",
    "config",
    "docs",
    "web/src",
    "web/package.json",
    "web/package-lock.json",
    "README.md",
    "AGENTS.md",
    "pyproject.toml",
    ".gitignore",
]

EXCLUDE_PATTERNS = [
    "data/**",
    ".venv/**",
    "dist/**",
    "web/dist/**",
    "node_modules/**",
    "web/node_modules/**",
    "__pycache__/**",
    "*.egg-info/**",
    ".pytest_cache/**",
    "*.sqlite3",
    "*.db",
    "*.log",
    "*.zip",
]


def should_exclude(relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/")
    parts = normalized.split("/")
    if "__pycache__" in parts or ".pytest_cache" in parts or ".venv" in parts or "node_modules" in parts:
        return True
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in EXCLUDE_PATTERNS)


def iter_source_files(root: Path):
    for item in INCLUDE_ROOTS:
        path = root / item
        if not path.exists():
            continue
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            if not should_exclude(relative):
                yield path, relative
            continue
        for file_path in sorted(path.rglob("*")):
            if not file_path.is_file():
                continue
            relative = file_path.relative_to(root).as_posix()
            if not should_exclude(relative):
                yield file_path, relative


def create_archive(root: Path, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path, relative in iter_source_files(root):
            archive.write(file_path, relative)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a clean Tasker source archive.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("dist/tasker-source.zip"))
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else args.root / args.output
    print(create_archive(args.root.resolve(), output.resolve()))


if __name__ == "__main__":
    main()
