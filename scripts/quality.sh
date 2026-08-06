#!/bin/sh
set -eu

python -m compileall -q envsbot.py bot core_plugins plugins database utils
python scripts/check_command_docs.py
ruff check .
mypy \
  database/outbox.py \
  database/command_usage.py \
  utils/outbox.py \
  utils/runtime_watchdog.py \
  utils/admin_reports.py
pip-audit -r requirements.txt
