#!/usr/bin/env python3
"""CLI wrapper for command-documentation validation."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.command_docs import validate_command_docs  # noqa: E402


def main() -> int:
    errors, command_count = validate_command_docs()
    if errors:
        print("Command docs check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Command docs check passed ({command_count} decorated commands).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
