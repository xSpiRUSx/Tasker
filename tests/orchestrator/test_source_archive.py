import importlib.util
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_archive_module():
    spec = importlib.util.spec_from_file_location("create_source_archive", ROOT / "scripts" / "create_source_archive.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_source_archive_excludes_runtime_data(tmp_path):
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "config").mkdir()
    (root / "web" / "src").mkdir(parents=True)
    (root / "web" / "dist").mkdir(parents=True)
    (root / "web" / "node_modules" / "vite").mkdir(parents=True)
    (root / "dist").mkdir()
    (root / "data" / "worktrees").mkdir(parents=True)
    (root / "data" / "obsidian-tasks").mkdir(parents=True)
    (root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (root / "config" / "projects.yml").write_text("projects: []\n", encoding="utf-8")
    (root / "web" / "src" / "App.tsx").write_text("export default function App() { return null }\n", encoding="utf-8")
    (root / "web" / "package.json").write_text("{}\n", encoding="utf-8")
    (root / "web" / "package-lock.json").write_text("{}\n", encoding="utf-8")
    (root / "web" / "dist" / "bundle.js").write_text("build\n", encoding="utf-8")
    (root / "web" / "node_modules" / "vite" / "index.js").write_text("deps\n", encoding="utf-8")
    (root / "dist" / "old.zip").write_text("zip\n", encoding="utf-8")
    (root / "config.zip").write_text("zip\n", encoding="utf-8")
    (root / "data" / "worktrees" / "runtime.txt").write_text("runtime\n", encoding="utf-8")
    (root / "data" / "obsidian-tasks" / "artifact.md").write_text("runtime\n", encoding="utf-8")
    (root / "data" / "orchestrator.sqlite3").write_text("db\n", encoding="utf-8")
    for name in ["README.md", "AGENTS.md", "pyproject.toml", ".gitignore"]:
        (root / name).write_text(name, encoding="utf-8")

    module = load_archive_module()
    archive_path = module.create_archive(root, tmp_path / "source.zip")

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())

    assert "src/app.py" in names
    assert "tests/test_app.py" in names
    assert "web/src/App.tsx" in names
    assert "web/package.json" in names
    assert "web/package-lock.json" in names
    assert not any(name.startswith("data/") for name in names)
    assert not any(name.startswith("web/dist/") for name in names)
    assert not any("node_modules" in name for name in names)
    assert not any(name.startswith("dist/") for name in names)
    assert "config.zip" not in names
