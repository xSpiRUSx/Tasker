from __future__ import annotations

import subprocess
from pathlib import Path


class GitService:
    def create_worktree(
        self,
        project_path: Path,
        worktrees_root: Path,
        task_id: str,
        branch_name: str,
        base_branch: str = "main",
    ) -> Path:
        if not project_path.exists():
            raise FileNotFoundError(f"Project path does not exist: {project_path}")
        worktrees_root.mkdir(parents=True, exist_ok=True)
        worktree_path = worktrees_root / task_id
        if worktree_path.exists():
            raise FileExistsError(f"Worktree already exists: {worktree_path}")

        start_point = base_branch if self._ref_exists(project_path, base_branch) else "HEAD"
        result = subprocess.run(
            ["git", "-C", str(project_path), "worktree", "add", "-b", branch_name, str(worktree_path), start_point],
            check=False,
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return worktree_path

    def is_repository(self, path: Path) -> bool:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            check=False,
            text=True,
            capture_output=True,
        )
        return result.returncode == 0

    def status(self, worktree_path: Path) -> str:
        return self._git(worktree_path, ["status", "--short"])

    def changed_files(self, worktree_path: Path) -> list[str]:
        output = self._git(worktree_path, ["diff", "--name-only", "HEAD"])
        return [line for line in output.splitlines() if line.strip()]

    def diff_stat(self, worktree_path: Path) -> str:
        return self._git(worktree_path, ["diff", "--stat", "HEAD"])

    def diff_patch(self, worktree_path: Path) -> str:
        return self._git(worktree_path, ["diff", "HEAD"])

    def commit(self, worktree_path: Path, message: str) -> str:
        check = subprocess.run(["git", "-C", str(worktree_path), "diff", "--check"], check=False, text=True, capture_output=True)
        if check.returncode != 0:
            raise RuntimeError(check.stderr.strip() or check.stdout.strip())
        subprocess.run(["git", "-C", str(worktree_path), "add", "-A"], check=False, text=True, capture_output=True)
        result = subprocess.run(["git", "-C", str(worktree_path), "commit", "-m", message], check=False, text=True, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return self._git(worktree_path, ["rev-parse", "HEAD"]).strip()

    def _git(self, worktree_path: Path, args: list[str]) -> str:
        result = subprocess.run(["git", "-C", str(worktree_path), *args], check=False, text=True, capture_output=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return result.stdout

    def _ref_exists(self, repository_path: Path, ref: str) -> bool:
        result = subprocess.run(
            ["git", "-C", str(repository_path), "rev-parse", "--verify", "--quiet", ref],
            check=False,
            text=True,
            capture_output=True,
        )
        return result.returncode == 0
