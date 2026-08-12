# Repository helper scripts

The `scripts/` directory contains repository-maintenance, deployment, release, and validation helpers for envsbot.

Run these commands from the repository root unless a script explicitly says otherwise. Use the project virtual environment for Python-based tooling so the same dependencies and constraints as CI are available.

## Script index

| Script | Purpose | Common usage |
| --- | --- | --- |
| `deploy.sh` | Preservation-first installation and release-update entrypoint. Bare invocation only shows help. | `./scripts/deploy.sh status`, `./scripts/deploy.sh check`, `./scripts/deploy.sh update --dry-run` |
| `deploy.py` | Python backend used by `deploy.sh`; normally do not invoke it directly. | Use `deploy.sh` instead. |
| `quality.sh` | Runs the local release-quality gates: compilation, generated-doc/config checks, Ruff, mypy, dependency validation/audit, and related checks. | `./scripts/quality.sh`, `./scripts/quality.sh --fix` |
| `test.sh` | Runs the warning-strict pytest suite with compact output; coverage is optional so normal developer loops stay fast without skipping tests. | `./scripts/test.sh`, `./scripts/test.sh --coverage`, `./scripts/test.sh --last-failed`, `./scripts/test.sh --durations 25` |
| `mutmut.sh` | Safe wrapper around mutation testing that prevents imports from the unmutated checkout. | `./scripts/mutmut.sh fresh`, `./scripts/mutmut.sh results` |
| `update-constraints.sh` | Reproduces or refreshes the complete Python 3.12/3.13 dependency snapshots. | `./scripts/update-constraints.sh 3.13`, `./scripts/update-constraints.sh 3.13 --refresh` |
| `check_constraints.py` | Verifies that a constraint snapshot pins the complete installed dependency closure. | `python scripts/check_constraints.py constraints/python313.txt` |
| `generate_config_sample.py` | Generates `config_sample.py` from the declarative configuration schema or checks that it is current. | `python scripts/generate_config_sample.py`, `python scripts/generate_config_sample.py --check` |
| `generate_commands_md.py` | Regenerates the checked-in command documentation from registered command metadata. | `python scripts/generate_commands_md.py` |
| `check_command_docs.py` | Validates that the checked-in generated command documentation matches the current command registry. | `python scripts/check_command_docs.py` |
| `check_wheel.py` | Smoke-tests the single built envsbot wheel and verifies packaged runtime assets. | `rm -rf dist && python -m build && python scripts/check_wheel.py` |

## Which helper should I use?

For normal installation, upgrades, systemd validation, and path discovery, start with [`deploy.sh`](../docs/deployment.md).

For the final checks before tagging a release, follow the [`release checklist`](../docs/release-checklist.md) rather than running individual helpers ad hoc.

For dependency-snapshot maintenance, see [`constraints/README.md`](../constraints/README.md).

Generated files such as `config_sample.py` and the generated command documentation should not be edited independently of their source metadata. Regenerate them with the helpers above and let `quality.sh` verify that the checked-in copies are current.

`deploy.py` is intentionally kept separate from the shell entrypoint so the deployment workflow can be tested thoroughly in Python while `deploy.sh` remains a small, executable operator interface.
