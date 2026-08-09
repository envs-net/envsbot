# envsbot Test Suite

This directory contains tests for the envsbot project.

## Structure

- `bot/` — tests for bot core and event handlers
- `database/` — tests for database managers and caching
- `plugins/` and `core_plugins/` — plugin integration and plugin-specific logic
- `utils/` — utilities, helpers, rate limiting, etc.

## Running Tests

You should have `pytest` and `pytest-asyncio` installed.

```bash
pip install -r requirements-dev.txt
pytest
```

## Guidelines

- Write new tests under the appropriate directory.
- Use fixtures from `conftest.py` as needed.
- Place test config (test DB path, temp files) under `tests/`.
- Async tests: use `async def` with the `pytest.mark.asyncio` marker.

## Mutation testing

Install development requirements and run:

```bash
./scripts/mutmut.sh fresh
./scripts/mutmut.sh results
./scripts/mutmut.sh browse
```

Mutmut source paths are configured in `pyproject.toml` because the repository uses a flat module plus package-directory layout. Do not set `PYTHONPATH` to the repository root for mutmut 3: pytest runs inside `./mutants`, and the original checkout would otherwise shadow the mutated modules. Mutation generation is restricted to lines exercised by the clean test suite (`mutate_only_covered_lines = true`); uncovered code remains a normal coverage gap instead of producing misleading branch survivors. Exact `log`/`logger` calls are excluded from mutation because their wording is telemetry, while returned, reply and admin-alert text remains mutable. Use `fresh` after mutation configuration or broad test-suite changes; normal follow-up runs can use `./scripts/mutmut.sh run`.
