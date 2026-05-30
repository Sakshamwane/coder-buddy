import pathlib
import subprocess
from contextvars import ContextVar
from typing import Tuple

from langchain_core.tools import tool

_DEFAULT_PROJECT_ROOT = pathlib.Path.cwd() / "generated_project"
_project_root_var: ContextVar[pathlib.Path] = ContextVar(
    "project_root", default=_DEFAULT_PROJECT_ROOT
)

# Kept for backward-compat with CLI (main.py)
PROJECT_ROOT = _DEFAULT_PROJECT_ROOT


def get_project_root() -> pathlib.Path:
    return _project_root_var.get()


def safe_path_for_project(path: str) -> pathlib.Path:
    root = get_project_root().resolve()
    p = (get_project_root() / path).resolve()
    if root not in p.parents and root != p.parent and root != p:
        raise ValueError("Attempt to write outside project root")
    return p


@tool
def write_file(path: str, content: str) -> str:
    """Writes content to a file at the specified path within the project root."""
    p = safe_path_for_project(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return f"WROTE:{p}"


@tool
def read_file(path: str) -> str:
    """Reads content from a file at the specified path within the project root."""
    p = safe_path_for_project(path)
    if not p.exists():
        return ""
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


@tool
def get_current_directory() -> str:
    """Returns the current working directory."""
    return str(get_project_root())


@tool
def list_files(directory: str = ".") -> str:
    """Lists all files in the specified directory within the project root."""
    p = safe_path_for_project(directory)
    if not p.is_dir():
        return f"ERROR: {p} is not a directory"
    files = [str(f.relative_to(get_project_root())) for f in p.glob("**/*") if f.is_file()]
    return "\n".join(files) if files else "No files found."


@tool
def run_cmd(cmd: str, cwd: str = None, timeout: int = 30) -> Tuple[int, str, str]:
    """Runs a shell command in the specified directory and returns the result."""
    cwd_dir = safe_path_for_project(cwd) if cwd else get_project_root()
    res = subprocess.run(cmd, shell=True, cwd=str(cwd_dir), capture_output=True, text=True, timeout=timeout)
    return res.returncode, res.stdout, res.stderr


def init_project_root():
    root = get_project_root()
    root.mkdir(parents=True, exist_ok=True)
    return str(root)
