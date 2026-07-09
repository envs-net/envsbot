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
- `docs/maintenance.md`
- `SECURITY.md`
- `CONTRIBUTING.md`
- `config_sample.py`

Check that installation and update instructions mention tagged releases and do
not recommend running a production bot from `main`.

## Test suite

Run the full offline test suite:

```bash
PYTHONPATH="$PWD" pytest --no-cov -q
PYTHONPATH="$PWD" pytest --cov=envsbot --cov-report=term-missing
```

Run mutation tests when practical:

```bash
PYTHONPATH="$PWD" mutmut run
PYTHONPATH="$PWD" mutmut results
```

Investigate any new `no tests` results before tagging. Long-lived surviving
mutants should be reviewed, but not every survivor is necessarily a release
blocker.

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
,restore last confirm
```

## GitHub / mirror checks

Check GitHub community standards and code scanning findings after pushing the
release preparation commits. Fix real findings before tagging. Dismiss only
findings that have been reviewed and are clearly false positives.

## Tagging

Update the version in `pyproject.toml` and `utils/version.py` if needed, then create and push the tag:

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin main
git push origin vX.Y.Z
```

After pushing, verify that the release page shows the new tag and update the
release notes before announcing the release.
