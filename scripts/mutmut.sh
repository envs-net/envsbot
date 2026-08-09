#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"

# mutmut 3 runs pytest from its generated ./mutants checkout.  Pointing
# PYTHONPATH back at the original repository makes pytest import unmutated
# modules and produces misleading "survived" / "no tests" results.
unset PYTHONPATH

command=${1:-run}
if [ "$#" -gt 0 ]; then
    shift
fi

case "$command" in
    fresh)
        rm -rf mutants
        set -- run "$@"
        ;;
    run|results|browse)
        set -- "$command" "$@"
        ;;
    *)
        printf 'Usage: %s [fresh|run|results|browse] [mutmut arguments...]\n' "$0" >&2
        exit 2
        ;;
esac

exec mutmut "$@"
