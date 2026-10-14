"""Convert submitted form measurements to the application's metric units."""

import math


FEET_TO_METERS = 0.3048
POUNDS_TO_KILOGRAMS = 0.45359237
PSI_TO_BAR = POUNDS_TO_KILOGRAMS * 9.80665 / 0.0254 ** 2 / 100000


def metric_measurement(value, unit, minimum, maximum):
    if value is None or str(value).strip() == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    if unit == "ft":
        parsed *= FEET_TO_METERS
    elif unit == "lb":
        parsed *= POUNDS_TO_KILOGRAMS
    elif unit == "psi":
        parsed *= PSI_TO_BAR
    elif unit == "f":
        parsed = (parsed - 32) * 5 / 9
    if unit in ("ft", "lb", "psi", "f"):
        parsed = round(parsed, 10)
    return max(minimum, min(maximum, parsed))
