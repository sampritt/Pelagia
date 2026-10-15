"""Consistent numeric formatting for dive metrics and share previews."""

import math


def format_metric(value, *, weight=False):
    """Round for display only, using half units for weight and whole units otherwise."""
    scale = 2 if weight else 1
    rounded = math.floor(float(value) * scale + 0.5) / scale
    return str(int(rounded)) if rounded.is_integer() else str(rounded)
