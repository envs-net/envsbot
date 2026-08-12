#!/bin/sh
set -eu

ruff_fix_args=""
if [ "${1:-}" = "--fix" ]; then
  ruff_fix_args="--fix"
  shift
fi
if [ "$#" -ne 0 ]; then
  echo "usage: $0 [--fix]" >&2
  exit 2
fi

python -m compileall -q envsbot.py bot core_plugins plugins database utils scripts
python scripts/check_command_docs.py
python scripts/generate_config_sample.py --check

# Repository-wide correctness-critical rules.
ruff check $ruff_fix_args .

# Keep unused imports out of normal modules and tests so local quality
# catches the same dead-import class that CodeQL reports. Package
# __init__.py files are excluded because several intentionally expose
# type-only/dynamic compatibility facades.
ruff check $ruff_fix_args --select F401 --extend-exclude '**/__init__.py' .

# Apply modernisation/import/bugbear and type checks to every production
# package. Passing directories keeps this gate future-proof: newly-added
# runtime modules are checked automatically instead of depending on a curated
# allow-list that can silently fall behind.
runtime_targets="envsbot.py bot core_plugins plugins database utils scripts"
ruff check $ruff_fix_args --select I,UP,B $runtime_targets

mypy $runtime_targets

python_minor=$(python -c 'import sys; print(f"{sys.version_info.major}{sys.version_info.minor}")')
constraint_file="constraints/python${python_minor}.txt"
if [ ! -f "$constraint_file" ]; then
  echo "No audited dependency snapshot for Python ${python_minor}" >&2
  exit 1
fi
pip-audit -r "$constraint_file"
