#!/usr/bin/env python3
"""Generate config_sample.py from the declarative configuration schema."""

from __future__ import annotations

import argparse
import pprint
import runpy
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "config_sample.py"
_SCHEMA = runpy.run_path(str(ROOT / "utils" / "config" / "spec.py"))
CONFIG_DISPLAY_SECTIONS = _SCHEMA["CONFIG_DISPLAY_SECTIONS"]
CONFIG_FIELDS = _SCHEMA["CONFIG_FIELDS"]
NESTED_CONFIG_FIELDS = _SCHEMA["NESTED_CONFIG_FIELDS"]
MISSING = _SCHEMA["MISSING"]


def _comment(text: str) -> list[str]:
    return [f"# {line}" if line else "#" for line in textwrap.wrap(text, width=84)]


def _render_value(value: object) -> list[str]:
    rendered = pprint.pformat(value, width=100, sort_dicts=False)
    return rendered.splitlines()



def _render_nested_value(group: str) -> list[str]:
    lines = ["{"]
    for key, field in NESTED_CONFIG_FIELDS[group].items():
        lines.extend(f"    {line}" for line in _comment(field.description))
        rendered = _render_value(field.default)
        lines.append(f"    {key!r}: {rendered[0]},")
        lines.extend(f"    {line}" for line in rendered[1:])
    lines.append("}")
    return lines


def render_config_sample() -> str:
    by_python_key = {field.python_key: field for field in CONFIG_FIELDS.values()}
    lines = [
        "# ================= ENVSBOT CONFIG SAMPLE =================",
        "#",
        "# Generated from utils/config/spec.py. Do not edit this sample by hand;",
        "# change the schema and run scripts/generate_config_sample.py instead.",
        "# Copy this file to config.py and adjust it for your installation.",
        "# Keep config.py private: it contains your bot password and optional API keys.",
        "",
    ]
    for title, python_keys in CONFIG_DISPLAY_SECTIONS:
        lines.extend([f"# ================= {title.upper()} =================", ""])
        for python_key in python_keys:
            field = by_python_key[python_key]
            if field.description:
                lines.extend(_comment(field.description))
            if field.startup_only:
                lines.append("# Startup-only: restart envsbot after changing this value.")
            value = field.sample if field.sample is not MISSING else field.default
            if value is MISSING:
                raise RuntimeError(f"No sample value declared for {python_key}")
            normalized_key = python_key.lower()
            if normalized_key in NESTED_CONFIG_FIELDS:
                rendered = _render_nested_value(normalized_key)
            else:
                rendered = _render_value(value)
            lines.append(f"{python_key} = {rendered[0]}")
            lines.extend(rendered[1:])
            lines.append("")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when config_sample.py differs from the declarative schema",
    )
    args = parser.parse_args()
    rendered = render_config_sample()
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != rendered:
            print("config_sample.py is out of date; run scripts/generate_config_sample.py")
            return 1
        print("config_sample.py matches utils/config/spec.py")
        return 0
    TARGET.write_text(rendered, encoding="utf-8")
    print(f"updated {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
