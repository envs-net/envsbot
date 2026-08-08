"""Resolve read-only assets shipped with both source and wheel installs."""

from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]

_BUNDLED_DIR = Path(__file__).resolve().parent / "bundled"


def resolve_bundled_asset(
    value: str | Path,
    *,
    base_dir: Path | None = None,
) -> Path:
    """Resolve a configured read-only file with a packaged-asset fallback.

    Relative operator paths keep their historical application-root semantics.
    Only a plain filename falls back to the copy embedded below ``utils`` when
    the application-root copy is absent, which is the normal wheel-install
    layout.
    """
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()

    root = (BASE_DIR if base_dir is None else base_dir).resolve()
    application_path = (root / path).resolve()
    if application_path.exists() or len(path.parts) != 1:
        return application_path

    packaged_path = (_BUNDLED_DIR / path.name).resolve()
    return packaged_path if packaged_path.exists() else application_path


def bundled_asset(name: str) -> Path:
    """Return a required repository asset from source or installed package."""
    return resolve_bundled_asset(name)
