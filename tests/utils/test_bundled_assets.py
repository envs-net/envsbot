from pathlib import Path

from utils import bundled_assets


def test_resolve_bundled_asset_prefers_application_copy(monkeypatch, tmp_path):
    app = tmp_path / "app"
    packaged = tmp_path / "packaged"
    app.mkdir()
    packaged.mkdir()
    (app / "avatar.jpg").write_bytes(b"app")
    (packaged / "avatar.jpg").write_bytes(b"package")
    monkeypatch.setattr(bundled_assets, "_BUNDLED_DIR", packaged)

    resolved = bundled_assets.resolve_bundled_asset("avatar.jpg", base_dir=app)

    assert resolved == (app / "avatar.jpg").resolve()


def test_resolve_bundled_asset_falls_back_to_packaged_plain_filename(monkeypatch, tmp_path):
    app = tmp_path / "app"
    packaged = tmp_path / "packaged"
    app.mkdir()
    packaged.mkdir()
    (packaged / "avatar.jpg").write_bytes(b"package")
    monkeypatch.setattr(bundled_assets, "_BUNDLED_DIR", packaged)

    resolved = bundled_assets.resolve_bundled_asset("avatar.jpg", base_dir=app)

    assert resolved == (packaged / "avatar.jpg").resolve()


def test_resolve_bundled_asset_does_not_rewrite_operator_subpaths(monkeypatch, tmp_path):
    app = tmp_path / "app"
    packaged = tmp_path / "packaged"
    app.mkdir()
    packaged.mkdir()
    (packaged / "avatar.jpg").write_bytes(b"package")
    monkeypatch.setattr(bundled_assets, "_BUNDLED_DIR", packaged)

    resolved = bundled_assets.resolve_bundled_asset(Path("data/avatar.jpg"), base_dir=app)

    assert resolved == (app / "data/avatar.jpg").resolve()
