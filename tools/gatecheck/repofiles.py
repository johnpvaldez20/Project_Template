#!/usr/bin/env python3
# SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
# SPDX-License-Identifier: LicenseRef-UNSET

"""List the files that are repository content.

Git gives the list when the root is a work tree. A file that Git ignores
is not repository content. A directory walk is the fallback.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache"}
_GIT_ENV_DROP = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")


def list_files(root: Path) -> list[str]:
    """Return repository-relative posix paths in sorted order."""
    listed = _git_files(root)
    if listed is None:
        listed = _walk_files(root)
    return sorted(path for path in set(listed) if (root / path).is_file())


def git_env() -> dict[str, str]:
    """Return the environment for a git call that must find its own work tree."""
    return {key: value for key, value in os.environ.items() if key not in _GIT_ENV_DROP}


def _git_files(root: Path) -> list[str] | None:
    command = ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
    try:
        done = subprocess.run(command, capture_output=True, env=git_env(), check=False)
    except OSError:
        return None
    if done.returncode != 0:
        return None
    text = done.stdout.decode("utf-8", "surrogateescape")
    return [item for item in text.split("\0") if item]


def _walk_files(root: Path) -> list[str]:
    found: list[str] = []
    for directory, names, files in os.walk(root):
        names[:] = [name for name in names if name not in _SKIP_DIRS]
        for name in files:
            found.append((Path(directory) / name).relative_to(root).as_posix())
    return found
