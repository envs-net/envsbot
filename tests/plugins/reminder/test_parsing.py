from .helpers import (
    MY_TZ,
    AsyncMock,
    MagicMock,
    datetime,
    pytest,
    pytz,
    reminder,
)


@pytest.mark.parametrize("s,seconds", [
    ("5s", 5),
    ("2m", 120),
    ("1h", 3600),
    ("3d", 259200),
    ("1h30m", 5400),
    ("2d2h3m4s", 2 * 86400 + 2 * 3600 + 3 * 60 + 4),
    ("", None),
    ("bad", None),
    ("0s", None),
    ("xx3d", None),
])
def test_parse_duration(s, seconds):
    assert reminder.parse_duration(s) == seconds


def test_parse_absolute_datetime():
    # Use a fixed TZ
    dt, count = reminder.parse_absolute_datetime(
        ["2026-05-01", "14:30"], MY_TZ)
    assert dt is not None and count == 2
    assert dt.astimezone(pytz.UTC).hour == 12  # 14:30+0200 == 12:30Z
    dt2, count2 = reminder.parse_absolute_datetime(
        ["01.05.2026", "14:30"], MY_TZ)
    assert dt2 is not None and count2 == 2

    dt3, count3 = reminder.parse_absolute_datetime(
        ["2026-07-10", "13:23", "CEST", "test"], pytz.UTC)
    assert dt3 is not None and count3 == 3
    assert dt3.hour == 11 and dt3.minute == 23

    dt4, count4 = reminder.parse_absolute_datetime(
        ["2026-01-10", "13:23", "CET", "test"], pytz.UTC)
    assert dt4 is not None and count4 == 3
    assert dt4.hour == 12 and dt4.minute == 23

    dt5, count5 = reminder.parse_absolute_datetime(
        ["2026-01-10", "13:23", "Europe/Berlin", "test"], pytz.UTC)
    assert dt5 is not None and count5 == 3
    assert dt5.hour == 12 and dt5.minute == 23
    # Invalid
    dt, count = reminder.parse_absolute_datetime(["bad"], MY_TZ)
    assert dt is None


@pytest.mark.asyncio
async def test_parse_reminder_when_duration_and_datetime():
    # Duration, with message
    sec, msg, when = reminder.parse_reminder_when(["1h", "test"], MY_TZ)
    assert sec is not None and msg == "test" and when.startswith("in ")
    # Absolute datetime, in future
    utcnow = datetime.datetime.now(pytz.UTC)
    # Convert to your test's timezone
    local_now = utcnow.astimezone(MY_TZ)
    local_dt = local_now + datetime.timedelta(hours=1)
    future = local_dt.strftime("%Y-%m-%d %H:%M")
    args = future.split() + ["something"]
    sec, msg, when = reminder.parse_reminder_when(args, MY_TZ)
    assert sec is not None and msg == "something"
    # Invalid cases
    assert reminder.parse_reminder_when([], MY_TZ) == (None, None, None)
    assert reminder.parse_reminder_when(["5s"], MY_TZ) == (None, None, None)


def test_parse_reminder_when_explicit_timezone(monkeypatch):
    fixed_now = datetime.datetime(2026, 7, 10, 10, 0, tzinfo=datetime.timezone.utc)
    monkeypatch.setattr(reminder, "_utcnow", lambda: fixed_now)

    sec, msg, when = reminder.parse_reminder_when(
        ["2026-07-10", "13:23", "CEST", "TEST1"],
        pytz.UTC,
    )

    assert sec == 4980
    assert msg == "TEST1"
    assert when == "on 2026-07-10 13:23 CEST"


def test_timezone_from_token_and_default_config(monkeypatch):
    assert reminder._timezone_from_token("CEST").utcoffset(None).total_seconds() == 7200
    assert reminder._timezone_from_token("CET").utcoffset(None).total_seconds() == 3600
    assert str(reminder._timezone_from_token("Europe/Berlin")) == "Europe/Berlin"
    assert reminder._timezone_from_token("+02:30").utcoffset(None).total_seconds() == 9000
    assert reminder._timezone_from_token("Mars/Base") is None

    monkeypatch.setitem(reminder.config, "reminder_default_timezone", "Europe/Berlin")
    assert str(reminder._reminder_default_tzinfo()) == "Europe/Berlin"

    monkeypatch.setitem(reminder.config, "reminder_default_timezone", "Invalid/Zone")
    assert str(reminder._reminder_default_tzinfo()) == "UTC"


@pytest.mark.asyncio
async def test_get_reminder_tzinfo_uses_user_timezone_or_config_default(monkeypatch, dummy_bot):
    store = MagicMock()
    store.get = AsyncMock(return_value="UTC")
    dummy_bot.db.users.plugin.return_value = store
    assert str(await reminder.get_reminder_tzinfo(dummy_bot, "u@example.org")) == "UTC"

    store.get = AsyncMock(return_value=None)
    monkeypatch.setitem(reminder.config, "reminder_default_timezone", "Europe/Berlin")
    assert str(await reminder.get_reminder_tzinfo(dummy_bot, "u@example.org")) == "Europe/Berlin"

    store.get = AsyncMock(side_effect=RuntimeError("db"))
    assert str(await reminder.get_reminder_tzinfo(dummy_bot, "u@example.org")) == "Europe/Berlin"


def test_format_seconds():
    assert reminder.format_seconds(3661) == "1h 1m 1s"
    assert reminder.format_seconds(61) == "1m 1s"
    assert reminder.format_seconds(-1) == "overdue"


def test_format_overdue():
    assert reminder._format_overdue(-59) == "59s ago"
    assert reminder._format_overdue(-61) == "1m ago"
    assert reminder._format_overdue(-3700) == "1.0h ago"
    assert reminder._format_overdue(-90000) == "1.0d ago"


def test_timezone_lookup_jid_direct_muc_plugin_joined_and_fallback(dummy_bot, monkeypatch):
    msg = MagicMock()
    from_jid = MagicMock(bare="user@example.org", resource="Nick")
    msg.__getitem__.side_effect = lambda key: {"from": from_jid, "type": "chat"}[key]

    assert reminder._timezone_lookup_jid(dummy_bot, "sender@example.org/res", msg, False) == "user@example.org"

    muc = MagicMock()
    muc.get_jid_property.return_value = "real@example.org/resource"
    dummy_bot.plugin = {"xep_0045": muc}
    from_jid.bare = "room@conf"
    from_jid.resource = "Nick"
    assert reminder._timezone_lookup_jid(dummy_bot, "sender@example.org/res", msg, True) == "real@example.org"
    muc.get_jid_property.assert_called_once_with("room@conf", "Nick", "jid")

    muc.get_jid_property.side_effect = RuntimeError("lookup failed")
    reminder.JOINED_ROOMS["room@conf"] = {
        "nicks": {"Nick": {"jid": "joined@example.org/resource"}}
    }
    try:
        assert reminder._timezone_lookup_jid(dummy_bot, "sender@example.org/res", msg, True) == "joined@example.org"
    finally:
        reminder.JOINED_ROOMS.pop("room@conf", None)

    dummy_bot.plugin = {}
    assert reminder._timezone_lookup_jid(dummy_bot, "sender@example.org/res", msg, True) == "sender@example.org"

    monkeypatch.setattr(reminder, "_is_muc_pm", lambda _msg: False)
    msg.__getitem__.side_effect = KeyError("from")
    assert reminder._timezone_lookup_jid(dummy_bot, "fallback@example.org/res", msg, False) == "fallback@example.org"


def test_parse_reminder_when_allows_current_minute_grace(monkeypatch):
    fixed_now = datetime.datetime(
        2026, 7, 11, 7, 30, 45, tzinfo=datetime.timezone.utc)
    monkeypatch.setattr(reminder, "_utcnow", lambda: fixed_now)

    sec, msg, when = reminder.parse_reminder_when(
        ["2026-07-11", "09:30", "CEST", "Test"],
        pytz.UTC,
    )

    assert sec == 1
    assert msg == "Test"
    assert when == "on 2026-07-11 09:30 CEST"


def test_explain_invalid_reminder_time_for_past_timezone(monkeypatch):
    fixed_now = datetime.datetime(
        2026, 7, 11, 7, 30, 0, tzinfo=datetime.timezone.utc)
    monkeypatch.setattr(reminder, "_utcnow", lambda: fixed_now)

    detail = reminder.explain_invalid_reminder_time(
        ["2026-07-11", "09:30", "+03:00", "Test"],
        pytz.UTC,
    )

    assert detail is not None
    assert "Reminder time must be in the future" in detail
    assert "Parsed target: 2026-07-11 09:30 +03:00" in detail
    assert "Current time: 2026-07-11 10:30 +03:00" in detail
