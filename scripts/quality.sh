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

printf '%s\n' '[1/8] Python compilation'
python -m compileall -q envsbot.py bot core_plugins plugins database utils scripts

printf '%s\n' '[2/8] Command documentation'
python scripts/check_command_docs.py

printf '%s\n' '[3/8] Generated configuration sample'
python scripts/generate_config_sample.py --check

printf '%s\n' '[4/8] Ruff: repository checks'
ruff check $ruff_fix_args .

printf '%s\n' '[5/8] Ruff: unused imports (F401)'
# Keep unused imports out of normal modules and tests so local quality
# catches the same dead-import class that CodeQL reports. Package
# __init__.py files are excluded because several intentionally expose
# type-only/dynamic compatibility facades.
ruff check $ruff_fix_args --select F401 --extend-exclude '**/__init__.py' .

printf '%s\n' '[6/8] Ruff: imports, modernization, and Bugbear (I,UP,B)'
# Apply modernisation/import/bugbear and type checks to every production
# package. Passing directories keeps this gate future-proof: newly-added
# runtime modules are checked automatically instead of depending on a curated
# allow-list that can silently fall behind.
runtime_targets="envsbot.py bot core_plugins plugins database utils scripts"
ruff check $ruff_fix_args --select I,UP,B $runtime_targets

printf '%s\n' '[7/8] mypy: production source tree'
mypy $runtime_targets

printf '%s\n' '[8/8] Dependency audit (pip-audit)'
python_minor=$(python -c 'import sys; print(f"{sys.version_info.major}{sys.version_info.minor}")')
constraint_file="constraints/python${python_minor}.txt"
if [ ! -f "$constraint_file" ]; then
  echo "No audited dependency snapshot for Python ${python_minor}" >&2
  exit 1
fi
pip-audit -r "$constraint_file"

printf '%s\n' 'Quality checks passed (8/8).'
