# Dependency constraints

`python312.txt` and `python313.txt` are the reviewed dependency constraints used
by CI and documented production installs.  Direct project and development
dependencies are pinned so an unrelated package release cannot silently change
the selected tool/runtime version during a build.

Regenerate a fully resolved snapshot intentionally on a networked development
host with the matching interpreter:

```bash
scripts/update-constraints.sh 3.12
scripts/update-constraints.sh 3.13
```

The script uses the currently reviewed direct pins as constraints, resolves
`requirements.txt` plus `requirements-dev.txt` in a clean virtual environment,
and then writes the complete `pip freeze --all` result (excluding packaging
bootstrap tools) back to the matching constraints file. Review and commit the
resulting diff as a dedicated dependency update.

Always use the constraints file matching the Python minor version:

```bash
pip install -c constraints/python313.txt -r requirements.txt
```
