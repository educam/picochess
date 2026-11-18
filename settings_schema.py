"""Describe picochess.ini settings for the web settings page.

The schema is generated from the ``Configuration`` argument parser, so help
texts, choices, types and defaults stay in one place. This module only adds
presentation data: a section for each key, whether a change applies without a
restart, and whether the value is secret.
"""

from __future__ import annotations

import argparse
from typing import Any

from configuration import Configuration, str_to_bool

# Sections in display order: (id, title, description, keys).
SECTIONS: list[tuple[str, str, str, list[str]]] = [
    (
        "board",
        "E-board and clock",
        "The electronic board, the DGT clock and what the clock shows.",
        [
            "board-type",
            "dgt-port",
            "dgtpi",
            "clockside",
            "slow-slide",
            "disable-revelation-leds",
            "disable-et",
            "enable-capital-letters",
            "disable-short-notation",
            "disable-confirm-message",
            "ponder-interval",
            "rolling-display-normal",
            "rolling-display-ponder",
            "beep-config",
            "beep-some-level",
        ],
    ),
    (
        "engine",
        "Engine and book",
        "The engine PicoChess starts with and its opening book.",
        ["engine", "engine-level", "engine-menu-sort", "book", "show-engine"],
    ),
    (
        "game",
        "Game and player",
        "Time control, player details and how games are stored.",
        [
            "time",
            "def-timectrl",
            "depth",
            "node",
            "pgn-user",
            "pgn-elo",
            "rating-deviation",
            "pgn-file",
            "location",
            "continue-game",
            "alt-move",
            "premove",
            "flexible-analysis",
        ],
    ),
    (
        "tutor",
        "PicoTutor",
        "Move evaluation, hints, opening names and comments.",
        [
            "tutor-engine",
            "tutor-watcher",
            "tutor-coach",
            "tutor-explorer",
            "tutor-comment",
            "comment-factor",
            "tutor-brain-hint-display",
            "tutor-brain-reveal-text",
            "tutor-brain-reveal-display",
            "countdown-during-brain-display",
            "coach-analyser",
        ],
    ),
    (
        "sound",
        "Voice and sound",
        "Spoken moves, language and where sound is played.",
        [
            "language",
            "computer-voice",
            "user-voice",
            "speed-voice",
            "volume-voice",
            "audio-backend",
            "enable-setpieces-voice",
            "web-speech-local",
            "web-speech-remote",
            "web-audio-backend-remote",
        ],
    ),
    (
        "web",
        "Web client",
        "The web page: port, look and access.",
        ["web-server", "theme", "pieces", "web-board-theme", "allow-onboard-without-auth"],
    ),
    (
        "retro",
        "Retro engines (MAME)",
        "Emulated chess computers.",
        ["rspeed", "rsound", "rdisplay", "rwindow", "window-control-backend"],
    ),
    (
        "network",
        "Network, e-mail and remote engines",
        "Phone hotspot, Bluetooth pairing, e-mail and engines on other computers.",
        [
            "hotspot-ssid",
            "hotspot-pass",
            "bt-pair-pin",
            "bt-pair-timeout",
            "email",
            "smtp-server",
            "smtp-port",
            "smtp-user",
            "smtp-pass",
            "smtp-from",
            "smtp-encryption",
            "smtp-starttls",
            "mailgun-key",
            "engine-remote",
            "engine-remote-server",
            "engine-remote-home",
            "engine-remote-user",
            "engine-remote-pass",
            "engine-remote-key",
            "tutor-remote-engine",
            "remote-picochess-url",
            "online-decrement",
        ],
    ),
    (
        "system",
        "System and diagnostics",
        "Updates, logging and developer options.",
        [
            "log-level",
            "log-file",
            "event-loop-diagnostics",
            "enable-update",
            "enable-update-reboot",
            "enable-console",
        ],
    ),
]
OTHER_SECTION = ("other", "Other settings", "Settings PicoChess does not describe.")

# Settings read by the web server outside the argument parser.
EXTRA_SETTINGS: dict[str, dict[str, Any]] = {
    "allow-onboard-without-auth": {
        "kind": "bool",
        "default": "true",
        "help": "Allow the Wi-Fi onboarding page without a password from private networks.",
    },
    "hotspot-ssid": {"kind": "text", "default": "", "help": "Name of your phone hotspot, used by Wi-Fi > Hotspot."},
    "hotspot-pass": {"kind": "text", "default": "", "help": "Password of your phone hotspot."},
    "bt-pair-pin": {"kind": "text", "default": "0000", "help": "PIN used when pairing a phone over Bluetooth."},
    "bt-pair-timeout": {"kind": "int", "default": "40", "help": "Seconds to wait for Bluetooth pairing."},
}

# Settings the web server applies when they are saved; everything else is read at start-up.
APPLIES_NOW = {"web-audio-backend-remote"}
APPLIES_ON_RELOAD = {"theme", "pieces", "web-board-theme"}
SECRET_KEYS = {"smtp-pass", "mailgun-key", "engine-remote-pass", "hotspot-pass"}

# Values the web client offers where the parser accepts free text.
UI_CHOICES: dict[str, list[str]] = {
    "board-type": ["dgt", "certabo", "chesslink", "chessnut", "ichessone", "citrine", "osa", "noeboard"],
    "theme": ["auto", "light", "dark", "time"],
    "pieces": ["alpha", "berlin", "leipzig", "merida", "neo", "uscf"],
    "web-board-theme": ["natural_wood", "blue", "green", "metal", "newspaper", "soft", "wood"],
    "tutor-comment": ["off", "single", "all"],
}

_IGNORED_ACTIONS = (argparse._HelpAction, argparse._VersionAction)
_BOOL_TEXT = ("1", "true", "yes", "on", "0", "false", "no", "off")


def _section_by_key() -> dict[str, str]:
    return {key: section_id for section_id, _, _, keys in SECTIONS for key in keys}


def _describe_action(action: argparse.Action) -> dict[str, Any] | None:
    long_options = [option for option in action.option_strings if option.startswith("--")]
    if not long_options or isinstance(action, _IGNORED_ACTIONS):
        return None
    key = long_options[0][2:]
    entry: dict[str, Any] = {"key": key, "help": (action.help or "").replace("%%", "%")}
    if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
        # In picochess.ini a flag is "true" (given) or "false" (not given).
        entry["kind"] = "flag"
        entry["default"] = "false"
        return entry
    if action.choices is not None:
        entry["kind"] = "choice"
        entry["choices"] = [str(choice) for choice in action.choices]
    elif action.type is str_to_bool:
        entry["kind"] = "bool"
    elif action.type is int:
        entry["kind"] = "int"
    elif action.type is float:
        entry["kind"] = "float"
    else:
        entry["kind"] = "text"
    entry["default"] = "" if action.default is None else str(action.default).lower() if isinstance(
        action.default, bool
    ) else str(action.default)
    return entry


def build_schema(parser: Any | None = None) -> dict[str, Any]:
    """Return sections and per-key settings descriptions for the web client."""
    if parser is None:
        parser = Configuration().parser
    settings: dict[str, dict[str, Any]] = {}
    for action in parser._actions:
        entry = _describe_action(action)
        if entry is not None:
            settings[entry["key"]] = entry
    for key, extra in EXTRA_SETTINGS.items():
        settings.setdefault(key, {"key": key, **extra})

    sections = _section_by_key()
    for key, entry in settings.items():
        if key in UI_CHOICES and entry["kind"] == "text":
            entry["kind"] = "choice"
            entry["choices"] = list(UI_CHOICES[key])
            entry["strict"] = False  # the parser accepts other values too
        entry["section"] = sections.get(key, OTHER_SECTION[0])
        if key in APPLIES_NOW:
            entry["applies"] = "now"
        elif key in APPLIES_ON_RELOAD:
            entry["applies"] = "reload"
        else:
            entry["applies"] = "restart"
        entry["secret"] = key in SECRET_KEYS

    section_list = [
        {"id": section_id, "title": title, "description": description, "keys": [k for k in keys if k in settings]}
        for section_id, title, description, keys in SECTIONS
    ]
    other_keys = sorted(key for key, entry in settings.items() if entry["section"] == OTHER_SECTION[0])
    section_list.append(
        {"id": OTHER_SECTION[0], "title": OTHER_SECTION[1], "description": OTHER_SECTION[2], "keys": other_keys}
    )
    return {"sections": section_list, "settings": settings}


def validate_value(entry: dict[str, Any], value: str) -> str | None:
    """Return an error message when ``value`` is not valid for ``entry``."""
    kind = entry.get("kind")
    text = (value or "").strip()
    if kind in ("flag", "bool"):
        if text.lower() not in _BOOL_TEXT:
            return "Use true or false."
        return None
    if kind == "int":
        try:
            int(text)
        except ValueError:
            return "Use a whole number."
        return None
    if kind == "float":
        try:
            float(text)
        except ValueError:
            return "Use a number."
        return None
    if kind == "choice" and entry.get("strict", True):
        if text not in entry.get("choices", []):
            choices = entry.get("choices", [])
            shown = ", ".join(choices[:12]) + (" …" if len(choices) > 12 else "")
            return "Choose one of: %s." % shown
    return None


def validate_entries(schema: dict[str, Any], entries: list[dict[str, Any]]) -> dict[str, str]:
    """Validate enabled entries; disabled (commented) lines are not read by PicoChess."""
    errors: dict[str, str] = {}
    settings = schema["settings"]
    for item in entries:
        key = str(item.get("key", "")).strip()
        if not item.get("enabled") or key not in settings:
            continue
        error = validate_value(settings[key], str(item.get("value", "")))
        if error:
            errors[key] = error
    return errors
