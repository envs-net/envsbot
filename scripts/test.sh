#!/bin/sh
set -eu

coverage=0
last_failed=0
durations=""

usage() {
  cat <<'USAGE'
Usage: ./scripts/test.sh [options] [pytest target ...]

Run envsbot's warning-strict pytest suite with compact output.

Options:
  --coverage       Enable repository coverage and enforce the 85% floor.
  --last-failed    Re-run only tests that failed in the previous pytest run.
  --durations N    Show the N slowest tests (all selected tests still run).
  -h, --help       Show this help.

Examples:
  ./scripts/test.sh
  ./scripts/test.sh --coverage
  ./scripts/test.sh --last-failed
  ./scripts/test.sh --durations 25
  ./scripts/test.sh tests/plugins/rss
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --coverage)
      coverage=1
      shift
      ;;
    --last-failed)
      last_failed=1
      shift
      ;;
    --durations)
      if [ "$#" -lt 2 ] || ! case "$2" in *[!0-9]*|'') false;; *) true;; esac; then
        echo "test.sh: --durations requires a positive integer" >&2
        exit 2
      fi
      if [ "$2" -le 0 ]; then
        echo "test.sh: --durations requires a positive integer" >&2
        exit 2
      fi
      durations="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -* )
      echo "test.sh: unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      break
      ;;
  esac
done

if [ "$last_failed" -eq 1 ]; then
  set -- --lf "$@"
fi
if [ -n "$durations" ]; then
  set -- "--durations=$durations" --durations-min=0.1 "$@"
fi

# pyproject.toml intentionally keeps `pytest` release-safe by default. Override
# addopts here so quick developer/CI runs avoid coverage collection overhead,
# while still running every selected test with warning-strict behavior.
if [ "$coverage" -eq 1 ]; then
  exec pytest \
    -o addopts= \
    -q \
    -W error::RuntimeWarning \
    -W error::DeprecationWarning \
    --cov=. \
    --cov-report=term \
    --cov-fail-under=85 \
    "$@"
fi

exec pytest \
  -o addopts= \
  -q \
  -W error::RuntimeWarning \
  -W error::DeprecationWarning \
  "$@"
