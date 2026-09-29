# Dependency constraints

`python312.txt`, `python313.txt`, and `python314.txt` are fully resolved dependency
snapshots used for reproducible installs and dependency audits. They pin the complete
runtime/development dependency closure, including the default `envs-xmpp[omemo]` stack, not only packages named directly in
`requirements.txt` and `requirements-dev.txt`.

Reproduce the current reviewed snapshot intentionally on a networked development
host with the matching interpreter:

```bash
scripts/update-constraints.sh 3.12
scripts/update-constraints.sh 3.13
scripts/update-constraints.sh 3.14
```

To deliberately resolve newer versions within the declared requirement ranges,
use `--refresh` and review the resulting diff as a dedicated dependency update:

```bash
scripts/update-constraints.sh 3.12 --refresh
scripts/update-constraints.sh 3.13 --refresh
scripts/update-constraints.sh 3.14 --refresh
```

The update script installs into a clean virtual environment, writes the complete
`pip freeze --all` result (excluding bootstrap `pip`, `setuptools` and `wheel`),
and verifies the installed dependency closure with `scripts/check_constraints.py`.
CI performs the same closure check after installation so an indirect dependency
cannot silently become unpinned.

Always use the constraints file matching the Python minor version:

```bash
python -m pip install -c constraints/python314.txt -r requirements.txt
```
