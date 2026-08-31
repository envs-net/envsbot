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

printf '%s\n' '[1/9] Python compilation'
python -m compileall -q envsbot.py bot core_plugins plugins database utils scripts

printf '%s\n' '[2/9] Command documentation'
python scripts/check_command_docs.py

printf '%s\n' '[3/9] Generated configuration sample'
python scripts/generate_config_sample.py --check

printf '%s\n' '[4/9] Ruff: repository checks'
ruff check $ruff_fix_args .

printf '%s\n' '[5/9] Ruff: unused imports (F401)'
# Keep unused imports out of normal modules and tests so local quality
# catches the same dead-import class that CodeQL reports. Package
# __init__.py files are excluded because several intentionally expose
# type-only/dynamic compatibility facades.
ruff check $ruff_fix_args --select F401 --extend-exclude '**/__init__.py' .

printf '%s\n' '[6/9] Ruff: imports, modernization, and Bugbear (I,UP,B)'
# Apply modernisation/import/bugbear and type checks to every production
# package. Passing directories keeps this gate future-proof: newly-added
# runtime modules are checked automatically instead of depending on a curated
# allow-list that can silently fall behind.
runtime_targets="envsbot.py bot core_plugins plugins database utils scripts"
ruff check $ruff_fix_args --select I,UP,B $runtime_targets

printf '%s\n' '[7/9] mypy: production source tree'
mypy $runtime_targets

printf '%s\n' '[8/9] Git whitespace errors'
# Check the effective release diff locally, including staged/unstaged changes.
# On a clean CI checkout, validate the complete tracked tree so shallow clones
# without reachable tags still catch whitespace errors.
latest_tag=$(git describe --tags --abbrev=0 2>/dev/null || true)
if [ -n "$latest_tag" ]; then
  git diff --check "$latest_tag"
fi
git diff --check HEAD
if git diff --quiet HEAD --; then
  empty_tree=$(git hash-object -t tree /dev/null)
  git diff --check "$empty_tree" HEAD
fi

printf '%s\n' '[9/9] Dependency audit (pip-audit)'
python_minor=$(python -c 'import sys; print(f"{sys.version_info.major}{sys.version_info.minor}")')
constraint_file="constraints/python${python_minor}.txt"
if [ ! -f "$constraint_file" ]; then
  echo "No audited dependency snapshot for Python ${python_minor}" >&2
  exit 1
fi
pip-audit -r "$constraint_file"

printf '%s\n' 'Quality checks passed (9/9).'
