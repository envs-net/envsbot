#!/usr/bin/env python3
"""Smoke-test the built EnvsBot wheel using shared release tooling."""

from __future__ import annotations

from pathlib import Path

from _envs_xmpp_bootstrap import ensure_envs_xmpp

ensure_envs_xmpp()

from envs_xmpp_ops.release import WheelAsset, WheelCheckSpec, wheel_check_main  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SPEC = WheelCheckSpec(
    distribution="envsbot",
    wheel_glob="envsbot-*.whl",
    console_script="envsbot",
    entry_point="envsbot:cli",
    version_prefix="envsbot ",
    version_contains=("(envs-xmpp ",),
    assets=(
        WheelAsset(
            source="utils/bundled/init_chat_slang.csv",
            member="utils/bundled/init_chat_slang.csv",
            resolver="utils.bundled_assets:bundled_asset",
            resolver_argument="init_chat_slang.csv",
            expected_runtime_fragment="utils/bundled",
        ),
        WheelAsset(
            source="utils/bundled/avatar.jpg",
            member="utils/bundled/avatar.jpg",
            resolver="utils.bundled_assets:bundled_asset",
            resolver_argument="avatar.jpg",
            expected_runtime_fragment="utils/bundled",
        ),
    ),
    required_members=("config_sample.py", "vcard_sample.py"),
)


if __name__ == "__main__":
    raise SystemExit(wheel_check_main(root=ROOT, spec=SPEC))
