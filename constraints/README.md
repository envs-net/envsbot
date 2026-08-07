# Dependency constraints

`python312.txt` and `python313.txt` are the reviewed, fully resolved dependency
snapshots used by CI and documented production installs. They pin the complete
runtime/development dependency closure, not only packages named directly in
`requirements.txt` and `requirements-dev.txt`.

Reproduce the current reviewed snapshot intentionally on a networked development
host with the matching interpreter:

```bash
scripts/update-constraints.sh 3.12
scripts/update-constraints.sh 3.13
```

To deliberately resolve newer versions within the declared requirement ranges,
use `--refresh` and review the resulting diff as a dedicated dependency update:

```bash
scripts/update-constraints.sh 3.12 --refresh
scripts/update-constraints.sh 3.13 --refresh
```

The update script installs into a clean virtual environment, writes the complete
`pip freeze --all` result (excluding bootstrap `pip`, `setuptools` and `wheel`),
and verifies the installed dependency closure with `scripts/check_constraints.py`.
CI performs the same closure check after installation so an indirect dependency
cannot silently become unpinned.

Always use the constraints file matching the Python minor version:

```bash
python -m pip install -c constraints/python313.txt -r requirements.txt
```
