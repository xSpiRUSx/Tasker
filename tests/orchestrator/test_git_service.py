import subprocess

from engineering_orchestrator.services.git_service import GitService


def run_git(path, *args):
    result = subprocess.run(["git", "-C", str(path), *args], check=False, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout


def test_diff_includes_untracked_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init")
    run_git(repo, "config", "user.email", "tasker@example.local")
    run_git(repo, "config", "user.name", "Tasker Tests")
    (repo / "tracked.txt").write_text("before\n", encoding="utf-8")
    run_git(repo, "add", "tracked.txt")
    run_git(repo, "commit", "-m", "initial")

    (repo / "tracked.txt").write_text("after\n", encoding="utf-8")
    (repo / "new.txt").write_text("new content\n", encoding="utf-8")

    service = GitService()

    assert service.changed_files(repo) == ["new.txt", "tracked.txt"]
    entries = service.get_status_entries(repo)
    by_path = {entry.path: entry for entry in entries}
    assert by_path["new.txt"].is_untracked
    assert by_path["tracked.txt"].is_modified

    patch = service.diff_patch(repo)
    assert "new.txt" in patch
    assert "+new content" in patch
    assert "tracked.txt" in patch
    assert "+after" in patch
