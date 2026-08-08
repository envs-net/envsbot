# Contributing to EnvsBot

Thanks for your interest in contributing to EnvsBot. EnvsBot is an envs.net
project maintained by its project maintainer. The codebase has been developed
with help from ChatGPT and GitHub Copilot, but all contributions should still be
reviewed, tested, and understood by the person submitting them.

## Before You Start

Please read:

* [README.md](README.md)
* [docs/README.md](docs/README.md)
* [docs/commands.md](docs/commands.md)
* [docs/help.md](docs/help.md)

For security-sensitive issues, read [SECURITY.md](SECURITY.md) before opening a
public issue.

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install -r requirements-dev.txt
cp config_sample.py config.py
cp vcard_sample.py vcard.py
```

Edit `config.py` and `vcard.py` only for local development. Do not commit local
runtime configuration, secrets, databases, avatars, backups, coverage files, or
mutation-testing artifacts.

## Running Tests

Run the offline test suite:

```bash
PYTHONPATH="$PWD" pytest
```

Run with coverage:

```bash
PYTHONPATH="$PWD" pytest --cov=. --cov-report=term-missing
```

Optional mutation testing:

```bash
./scripts/mutmut.sh fresh
./scripts/mutmut.sh results
```

Do not set `PYTHONPATH` to the repository root for mutmut 3. Mutmut runs
pytest from its generated `./mutants` checkout, and forcing the original
checkout onto `PYTHONPATH` can cause tests to import unmodified source files.
Use `./scripts/mutmut.sh run` for normal follow-up runs after the initial fresh
run.

Live XMPP integration testing is opt-in and requires a dedicated test account
and rooms. Do not run destructive or spammy tests against production rooms.

## Pull Request Guidelines

A good pull request should:

* Describe what changed and why.
* Include tests for new behavior or bug fixes.
* Update documentation when commands, config, setup, roles, permissions, or
  user-facing behavior changes.
* Update `config_sample.py` when adding or changing config options.
* Regenerate `docs/commands.md` when command metadata changes.
* Keep unrelated refactors out of feature or bugfix pull requests.
* Avoid committing local runtime files such as `config.py`, `vcard.py`,
  databases, backups, `.coverage`, `.pytest_cache/`, `mutants/`, or generated
  test artifacts.

Before submitting:

```bash
PYTHONPATH="$PWD" pytest
```

Recommended for larger changes:

```bash
PYTHONPATH="$PWD" pytest --cov=. --cov-report=term-missing
./scripts/mutmut.sh fresh
./scripts/mutmut.sh results
```

## AI-Assisted Changes

AI tools such as ChatGPT and GitHub Copilot may be used, but please:

* Review generated code carefully.
* Make sure the code matches the project style and behavior.
* Run the relevant tests.
* Avoid submitting code you do not understand.
* Mention AI assistance in the pull request when it materially helped produce
  the change.

## Commit Messages

Use concise commit messages with a clear prefix when helpful:

```text
fix: harden users role handling
feat: add room plugin status command
test: cover reminder timezone edge cases
docs: update command help notes
chore: update CI config
```

## Maintainer Decisions

The maintainer may ask for changes, close issues, reject pull requests, or
choose a different implementation path. Please keep discussions constructive.
