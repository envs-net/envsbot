"""Load trusted local Python data files without creating ``__pycache__``."""

from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any


class _NoBytecodeSourceLoader(importlib.machinery.SourceFileLoader):
    """Source loader that deliberately never writes a ``.pyc`` file."""

    def set_data(
        self,
        path: str,
        data: bytes,
        *,
        _mode: int = 0o666,
    ) -> None:
        del path, data, _mode


def load_python_namespace(
    path: str | Path,
    *,
    module_name: str,
) -> dict[str, Any]:
    """Execute one trusted local Python file and return its namespace.

    Runtime operator files such as ``config.py`` and ``vcard.py`` are data
    sources rather than importable application modules. They retain normal
    Python module semantics without leaving bytecode caches beside writable
    configuration or runtime-data files.
    """
    source_path = Path(path)
    loader = _NoBytecodeSourceLoader(module_name, str(source_path))
    spec = importlib.util.spec_from_loader(module_name, loader)
    if spec is None:
        raise ImportError(f"Could not load Python source from {source_path}")
    module: ModuleType = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return vars(module)
