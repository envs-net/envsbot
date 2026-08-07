#!/bin/sh
set -eu

python -m compileall -q envsbot.py bot core_plugins plugins database utils
python scripts/check_command_docs.py
python scripts/generate_config_sample.py --check

# Repository-wide correctness-critical rules.
ruff check .

# Stricter modernisation/import/bugbear rules for the hardened core. Expand
# this list package-by-package so the CI gate grows without a mass style rewrite.
ruff check --select I,UP,B \
  core_plugins/config_cmd.py \
  core_plugins/doctor.py \
  core_plugins/users/roles.py \
  database/idlerpg.py \
  database/locking.py \
  database/outbox.py \
  database/command_usage.py \
  database/audit.py \
  database/users.py \
  database/message_cache.py \
  database/rooms.py \
  database/migrations \
  plugins/ducks.py \
  plugins/idlerpg/config.py \
  plugins/idlerpg/commands.py \
  plugins/idlerpg/export.py \
  plugins/idlerpg/leveling.py \
  plugins/idlerpg/state.py \
  plugins/idlerpg/tasks.py \
  plugins/rss/fetch.py \
  utils/command_execution.py \
  utils/config \
  utils/task_supervisor.py \
  utils/plugin_manager.py \
  utils/performance.py \
  utils/rate_limiter.py \
  utils/systemd_deploy.py \
  utils/outbox.py

mypy \
  database/idlerpg.py \
  database/locking.py \
  database/outbox.py \
  database/command_usage.py \
  database/audit.py \
  database/users.py \
  database/message_cache.py \
  database/rooms.py \
  database/migrations \
  plugins/idlerpg/config.py \
  plugins/idlerpg/commands.py \
  plugins/idlerpg/export.py \
  plugins/idlerpg/leveling.py \
  plugins/idlerpg/state.py \
  plugins/idlerpg/tasks.py \
  plugins/rss/fetch.py \
  utils/command_execution.py \
  utils/config \
  utils/task_supervisor.py \
  utils/plugin_manager.py \
  utils/performance.py \
  utils/rate_limiter.py \
  utils/backups.py \
  utils/outbox.py \
  utils/runtime_watchdog.py \
  utils/admin_reports.py

python_minor=$(python -c 'import sys; print(f"{sys.version_info.major}{sys.version_info.minor}")')
constraint_file="constraints/python${python_minor}.txt"
if [ ! -f "$constraint_file" ]; then
  echo "No audited dependency snapshot for Python ${python_minor}" >&2
  exit 1
fi
pip-audit -r "$constraint_file" --no-deps
