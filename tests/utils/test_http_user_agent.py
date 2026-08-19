from utils.http_user_agent import (
    LEGACY_DEFAULT_USER_AGENT,
    automatic_user_agent,
    resolve_user_agent,
)
from utils.version import normalized_version


def test_automatic_user_agent_tracks_runtime_version():
    assert automatic_user_agent() == (
        f"envsbot/{normalized_version()} (https://github.com/envs-net/envsbot)"
    )


def test_user_agent_version_token_is_expanded():
    assert resolve_user_agent("custom/{version}") == f"custom/{normalized_version()}"


def test_legacy_default_automatically_upgrades_to_versioned_agent():
    assert resolve_user_agent(LEGACY_DEFAULT_USER_AGENT) == automatic_user_agent()


def test_custom_user_agent_is_preserved():
    assert resolve_user_agent("operator-agent/1") == "operator-agent/1"
