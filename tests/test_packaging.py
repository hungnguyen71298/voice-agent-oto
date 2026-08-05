"""Every third-party module this code imports must be declared in requirements.txt.

A package that arrives only as someone else's transitive dependency works on the machine
that happens to have it and vanishes everywhere else. Both `av` and `loguru` did exactly
that: they imported fine in the dev venv and only failed inside the Docker image, ten
minutes into a build. This test moves that discovery to the second it takes to run pytest.
"""
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_DIRS = ["voice_agent", "scripts", "tests"]

# requirements name -> module name, where they differ.
DISTRIBUTION_TO_MODULE = {
    "pipecat-ai": "pipecat",
    "python-dotenv": "dotenv",
    "rank-bm25": "rank_bm25",
    "edge-tts": "edge_tts",
    "piper-tts": "piper",
}


def declared_modules() -> set[str]:
    """Module names provided by requirements.txt and requirements-dev.txt."""
    modules = set()
    for name in ("requirements.txt", "requirements-dev.txt"):
        for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
            line = line.split("#")[0].strip()
            if not line or line.startswith("-r"):
                continue
            dist = re.split(r"[\[<>=!;\s]", line)[0]
            modules.add(DISTRIBUTION_TO_MODULE.get(dist, dist.replace("-", "_")))
    return modules


def imported_modules() -> dict[str, set[str]]:
    """Top-level module name -> files importing it, across every source directory."""
    found: dict[str, set[str]] = {}
    for directory in SOURCE_DIRS:
        for path in (ROOT / directory).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                else:
                    continue
                for name in names:
                    found.setdefault(name.split(".")[0], set()).add(
                        str(path.relative_to(ROOT)))
    return found


def test_every_imported_package_is_declared():
    declared = declared_modules() | set(sys.stdlib_module_names) | {"voice_agent"}
    undeclared = {mod: sorted(files) for mod, files in imported_modules().items()
                  if mod not in declared}
    assert not undeclared, (
        f"imported but not in requirements: {undeclared}. "
        "Add them — relying on a transitive dependency breaks in a clean environment.")


def test_declared_packages_are_actually_installed():
    """Catches a typo in requirements.txt that pip silently resolves to nothing here."""
    import importlib.util
    missing = [m for m in declared_modules() if importlib.util.find_spec(m) is None]
    assert not missing, f"declared but not importable in this environment: {missing}"
