"""Load the project .env file, including files saved as UTF-16 by Windows tools."""
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


def load_project_env() -> bool:
    """Load the nearest project .env without printing or rewriting its contents."""
    candidates = (Path.cwd() / ".env", Path(__file__).resolve().parent / ".env")
    for path in candidates:
        if not path.is_file():
            continue
        for encoding in ("utf-8", "utf-8-sig", "utf-16"):
            try:
                return load_dotenv(dotenv_path=path, encoding=encoding)
            except UnicodeDecodeError:
                continue
    return False
