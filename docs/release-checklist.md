# Release checklist

Use this checklist before tagging a stable EnvsBot release.

## Release branch

`main` is the development branch. Production deployments should use the latest
stable tag, not a moving branch checkout.

Before cutting a release, make sure `main` is clean and all intended changes are
committed:

```bash
git status --short
git log --oneline --decorate -n 10
```

## Documentation

Regenerate the command reference after changing command decorators or
command decorator metadata:

```bash
python scripts/generate_commands_md.py
git diff -- docs/commands.md
```

Review at least:

- `README.md`
- `docs/README.md`
- `docs/commands.md`
- `docs/help.md`
- `docs/deployment.md`
- `docs/diagnostics.md`
- `docs/maintenance.md`
- `SECURITY.md`
- `CONTRIBUTING.md`
- `config_sample.py`

Check that installation and update instructions mention tagged releases and do
not recommend running a production bot from `main`.

## Test suite

Run the unified quality gate and the full warning-strict pytest suite from the
release checkout:

```bash
./scripts/quality.sh
pytest -W error::RuntimeWarning -W error::DeprecationWarning
```

Then build and smoke-test the exact wheel that would be released:

```bash
rm -rf build dist
python -m build
python scripts/check_wheel.py
```

The quality runner checks compilation, generated command/config documentation,
Ruff, the hardened Ruff import/modernisation/Bugbear rules, mypy, the audited
Python-version constraint snapshot and dependency advisories. The pytest
configuration enforces the repository coverage floor.

The wheel smoke test installs the built wheel into a temporary environment and
verifies that packaged runtime defaults such as `init_chat_slang.csv` and the
default avatar are available outside a source checkout.

Run the final mutation gate from a fresh mutant tree:

```bash
./scripts/mutmut.sh fresh
./scripts/mutmut.sh results
```

The final release mutation run must start from a fresh `mutants/` tree so cached results from earlier test/config revisions cannot leak into the release gate. Never set `PYTHONPATH` to the repository root for mutmut 3.

Investigate any new `no tests` results before tagging. Long-lived surviving
mutants should be reviewed, but not every survivor is necessarily a release
blocker.

## Deployment smoke test

On a representative systemd deployment, verify the preservation-first helper
against the installed paths before tagging:

```bash
./scripts/deploy.sh status
./scripts/deploy.sh check
./scripts/deploy.sh update --dry-run
```

`status` and `check` must resolve the expected application, virtualenv, config,
service account, database and unit paths. The update dry-run must select only a
stable release-tag workflow and must not stop the service or change files.

## Local smoke test

On a test bot account, verify the most important commands in a MUC, direct chat
and MUC private message where possible:

```text
,help
,help all
,plugins
,plugins list
,bot status
,bot status full
,version
,checkupdate
,config show
,config diff
,bot status full
,backup
,backup list
,rooms list
,rooms invite list
,doctor warnings
,doctor failed
,tasks failed
,tasks stale
,audit errors
,plugins
,plugin diagnose rss
,users admins
,users roles
```

For role handling, verify:

- Normal users cannot run admin commands.
- Admins cannot grant admin, superadmin or owner-level access.
- Superadmins can assign lower roles.
- The owner role comes only from `config.py`.
- Role changes and denied role changes are visible in the audit log.

## Backup and restore

Before a release, verify backup creation and listing:

```text
,backup
,backup show last
,backup list
```

Test restore only on a disposable instance:

```text
,backup restore-plan last
,restore last confirm
```

The restore command verifies and stages the selected archive before changing
runtime files, creates a checksum-verified safety backup, then fully quiesces
plugins/workers/outbox/cache/database before publishing restored state. It never
resumes the old Python process afterwards: success and post-quiesce failures both
lead to restart code `75`, so the generated recommended `Restart=on-failure` systemd unit
starts a fresh process. Configured `vcard.py` and `chat_slang.csv` files below
`RUNTIME_DATA_DIR` are restored with the database/config; legacy copies inside
the read-only application checkout remain in the archive for manual/offline
recovery. After quiescing, the exact closed runtime files are staged for rollback before restored state is published; the earlier verified safety backup remains an additional recovery point.

## GitHub / mirror checks

Check GitHub community standards and code scanning findings after pushing the
release preparation commits. Fix real findings before tagging. Dismiss only
findings that have been reviewed and are clearly false positives.

## Tagging

Update the version in `utils/version.py` if needed. The package metadata in
`pyproject.toml` reads the same value dynamically, so no second version field
needs to be maintained. Then create and push the tag:

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin main
git push origin vX.Y.Z
```

After pushing, verify that the release page shows the new tag and update the
release notes before announcing the release.
