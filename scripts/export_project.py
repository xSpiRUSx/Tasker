from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


INCLUDE_ROOTS = [
    "src",
    "tests",
    "config",
    "docs",
    "scripts",
]

INCLUDE_FILES = [
    ".gitignore",
    "AGENTS.md",
    "README.md",
    "pyproject.toml",
]

EXCLUDED_DIR_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "data",
    "dist",
    "htmlcov",
    "venv",
}

EXCLUDED_SUFFIXES = {
    ".db",
    ".log",
    ".pyc",
    ".pyo",
    ".sqlite3",
}


def should_include(path: Path, project_root: Path) -> bool:
    relative = path.relative_to(project_root)
    if any(part in EXCLUDED_DIR_NAMES for part in relative.parts):
        return False
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    if path.name.endswith(".egg-info"):
        return False
    return True


def iter_export_files(project_root: Path):
    for file_name in INCLUDE_FILES:
        path = project_root / file_name
        if path.is_file() and should_include(path, project_root):
            yield path

    for root_name in INCLUDE_ROOTS:
        root = project_root / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and should_include(path, project_root):
                yield path


def export_zip(project_root: Path, output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(set(iter_export_files(project_root)))
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(project_root).as_posix())
    return len(files)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a clean Tasker source export ZIP.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Project root. Defaults to the Tasker repository root.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output ZIP path. Defaults to <root>/dist/tasker-source.zip.",
    )
    args = parser.parse_args()

    project_root = args.root.resolve()
    output_path = (args.output or project_root / "dist" / "tasker-source.zip").resolve()
    count = export_zip(project_root, output_path)
    print(f"Exported {count} files to {output_path}")


if __name__ == "__main__":
    main()
