"""Validated multiple choices with compatibility for older single-choice dives."""

import json


DIVE_TYPES = ("open water", "shore dive", "reef", "wall", "deep", "drift", "night", "wreck", "cavern", "cave")
CURRENT_TYPES = ("none", "slack", "tidal", "surge", "drift", "rip", "upwelling", "downdraft")


def normalize_options(values, choices, default):
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        values = []
    selected = [choice for choice in choices if choice in values]
    if choices == CURRENT_TYPES and len(selected) > 1 and "none" in selected:
        selected.remove("none")
    return selected or [default]


def stored_options(dive, json_field, legacy_field, choices, default):
    raw = dive[json_field] if json_field in dive.keys() else None
    try:
        values = json.loads(raw) if raw is not None else dive[legacy_field]
    except (TypeError, ValueError):
        values = dive[legacy_field]
    return normalize_options(values, choices, default)


def dive_type_options(dive):
    return stored_options(dive, "dive_types_json", "dive_type", DIVE_TYPES, "open water")


def current_type_options(dive):
    return stored_options(dive, "current_types_json", "current", CURRENT_TYPES, "none")
