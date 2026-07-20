#!/usr/bin/env python3
"""CLI wrapper for generated command documentation."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.command_docs import write_generated_docs  # noqa: E402


def main() -> int:
    for path in write_generated_docs():
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
