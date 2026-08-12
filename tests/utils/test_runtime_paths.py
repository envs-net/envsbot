from utils import runtime_paths


def test_runtime_data_dir_keeps_legacy_app_root_when_unset(monkeypatch, tmp_path):
    project = tmp_path / "app"
    project.mkdir()
    monkeypatch.setattr(runtime_paths, "BASE_DIR", project)

    assert runtime_paths.runtime_data_dir({"db": "bot.db"}) == project
    assert runtime_paths.runtime_data_dir(
        {"db": str(tmp_path / "state" / "bot.db")}
    ) == project


def test_runtime_data_dir_explicit_override_wins(monkeypatch, tmp_path):
    project = tmp_path / "app"
    project.mkdir()
    monkeypatch.setattr(runtime_paths, "BASE_DIR", project)
    configured = tmp_path / "runtime"

    config = {
        "db": str(tmp_path / "db" / "bot.db"),
        "runtime_data_dir": str(configured),
    }
    assert runtime_paths.runtime_data_dir(config) == configured
    assert runtime_paths.vcard_file(config) == configured / "vcard.py"
    assert runtime_paths.chat_slang_file(config) == configured / "chat_slang.csv"
    assert runtime_paths.chat_slang_additions_file(config) == configured / "slang_additions.csv"
    assert runtime_paths.chat_slang_removals_file(config) == configured / "slang_removals.csv"
    assert runtime_paths.profile_state_file(config, "avatar_hash.asc") == configured / "avatar_hash.asc"
