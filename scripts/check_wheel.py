#!/usr/bin/env python3
"""Install the built wheel in isolation and verify packaged runtime assets."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ("init_chat_slang.csv", "avatar.jpg")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    wheels = sorted((ROOT / "dist").glob("envsbot-*.whl"))
    if len(wheels) != 1:
        print(f"Expected exactly one built envsbot wheel, found {len(wheels)}", file=sys.stderr)
        return 1
    wheel = wheels[0]

    expected = {name: _digest(ROOT / "utils" / "bundled" / name) for name in ASSETS}
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        for name in ASSETS:
            member = f"utils/bundled/{name}"
            if member not in names:
                print(f"Wheel is missing packaged asset: {member}", file=sys.stderr)
                return 1
            actual = hashlib.sha256(archive.read(member)).hexdigest()
            if actual != expected[name]:
                print(f"Wheel asset differs from canonical bundled source: {name}", file=sys.stderr)
                return 1

    with tempfile.TemporaryDirectory(prefix="envsbot-wheel-") as temp_name:
        temp = Path(temp_name)
        env_dir = temp / "venv"
        venv.EnvBuilder(with_pip=True, system_site_packages=True).create(env_dir)
        python = env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-deps",
                "--force-reinstall",
                str(wheel),
            ],
            cwd=temp,
            check=True,
        )
        code = """
from pathlib import Path
from utils.bundled_assets import bundled_asset

for name in ("init_chat_slang.csv", "avatar.jpg"):
    path = bundled_asset(name)
    assert path.is_file(), (name, path)
    assert "utils/bundled" in path.as_posix(), (name, path)
print("Wheel asset smoke test passed.")
"""
        subprocess.run([str(python), "-c", code], cwd=temp, check=True)

    print(f"Wheel smoke test passed: {wheel.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
