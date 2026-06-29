from __future__ import annotations

import subprocess
from pathlib import Path

from pydantic import BaseModel


class GitStatusEntry(BaseModel):
    path: str
    status: str
    is_untracked: bool = False
    is_deleted: bool = False
    is_modified: bool = False


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
        result = self._run_git(
            project_path,
            ["worktree", "add", "-b", branch_name, str(worktree_path), start_point],
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return worktree_path

    def is_repository(self, path: Path) -> bool:
        result = self._run_git(path, ["rev-parse", "--show-toplevel"])
        return result.returncode == 0

    def status(self, worktree_path: Path) -> str:
        return self._git(worktree_path, ["status", "--short"])

    def changed_files(self, worktree_path: Path) -> list[str]:
        return sorted({entry.path for entry in self.get_status_entries(worktree_path)})

    def get_status_entries(self, worktree_path: Path) -> list[GitStatusEntry]:
        output = self._git(worktree_path, ["status", "--porcelain"])
        entries: list[GitStatusEntry] = []
        for line in output.splitlines():
            if not line.strip():
                continue
            status = line[:2]
            path = line[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1].strip()
            entries.append(
                GitStatusEntry(
                    path=path,
                    status=status,
                    is_untracked=status == "??",
                    is_deleted="D" in status,
                    is_modified=any(marker in status for marker in ("M", "A", "R", "C", "?", "D")),
                )
            )
        return entries

    def diff_stat(self, worktree_path: Path) -> str:
        self._mark_untracked_for_diff(worktree_path)
        return self._git(worktree_path, ["diff", "--stat", "HEAD"])

    def diff_patch(self, worktree_path: Path) -> str:
        self._mark_untracked_for_diff(worktree_path)
        return self._git(worktree_path, ["diff", "HEAD"])

    def commit(self, worktree_path: Path, message: str) -> str:
        self.diff_check(worktree_path)
        self._run_git(worktree_path, ["add", "-A"])
        result = self._run_git(worktree_path, ["commit", "-m", message])
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return self._git(worktree_path, ["rev-parse", "HEAD"]).strip()

    def diff_check(self, worktree_path: Path) -> str:
        check = self._run_git(worktree_path, ["diff", "--check"])
        if check.returncode != 0:
            raise RuntimeError(check.stderr.strip() or check.stdout.strip())
        return check.stdout

    def _git(self, worktree_path: Path, args: list[str]) -> str:
        result = self._run_git(worktree_path, args)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return result.stdout

    def _mark_untracked_for_diff(self, worktree_path: Path) -> None:
        result = self._run_git(worktree_path, ["add", "--intent-to-add", "--", "."])
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())

    def _ref_exists(self, repository_path: Path, ref: str) -> bool:
        result = self._run_git(repository_path, ["rev-parse", "--verify", "--quiet", ref])
        return result.returncode == 0

    def _run_git(self, repository_path: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-c", "core.quotepath=false", "-C", str(repository_path), *args],
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )
