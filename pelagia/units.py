"""Convert measurements between stored metric values and display units."""

import math


FEET_TO_METERS = 0.3048
POUNDS_TO_KILOGRAMS = 0.45359237
PSI_TO_BAR = POUNDS_TO_KILOGRAMS * 9.80665 / 0.0254 ** 2 / 100000
UNIT_OPTIONS = {
    "pressure": ("bar", "psi"),
    "length": ("m", "ft"),
    "temperature": ("c", "f"),
    "weight": ("kg", "lb"),
}


def display_measurement(value, unit):
    """Convert without rounding or modifying the stored measurement."""
    if value is None or value == "":
        return None
    value = float(value)
    if unit == "ft":
        return value / FEET_TO_METERS
    if unit == "lb":
        return value / POUNDS_TO_KILOGRAMS
    if unit == "psi":
        return value / PSI_TO_BAR
    if unit == "f":
        return value * 9 / 5 + 32
    return value


def pressure_display(value, unit):
    """Use the requested full-cylinder labels without altering measurements."""
    converted = display_measurement(value, unit)
    if converted is None:
        return None
    if unit == "psi" and math.isclose(float(value), 200, abs_tol=1e-7):
        return 3000
    if unit == "bar" and math.isclose(float(value), 3000 * PSI_TO_BAR, abs_tol=1e-7):
        return 200
    return converted


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
    if not math.isfinite(parsed):
        return None
    if unit in ("ft", "lb", "psi", "f"):
        parsed = round(parsed, 10)
    return max(minimum, min(maximum, parsed))
