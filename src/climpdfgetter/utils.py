from pathlib import Path


def _find_project_root() -> str:
    """Find the project root directory."""
    root_dir = Path(__file__).resolve().parents[2]
    return str(root_dir)
