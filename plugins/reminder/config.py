"""Reminder plugin metadata and immutable settings."""

PLUGIN_META = {
    "name": "reminder",
    "version": "0.2.3",
    "description": "Schedule and manage reminders",
    "category": "utility",
    "requires": ["_core", "rooms"],
}

REMINDER_KEY = "REMINDER"
REMINDER_REPLY_FALLBACK_NAMESPACE = "reminder-reply-fallback"
