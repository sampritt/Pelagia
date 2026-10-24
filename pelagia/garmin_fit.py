"""Decode Garmin dive files without filesystem, Flask, or database access."""

import math
from datetime import datetime, timedelta, timezone

from garmin_fit_sdk import Decoder, Stream


MAX_FIT_BYTES = 10 * 1024 * 1024
MAX_PROFILE_POINTS = 100_000
FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)


class FitImportError(ValueError):
    """A file cannot be represented by the supported dive import."""


def finite_number(value, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        if not math.isfinite(value) or (minimum is not None and value < minimum):
            return None
    except OverflowError:
        return None
    return value


def _utc(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return None


def _first_number(*values):
    return next((number for value in values if (number := finite_number(value, 0)) is not None), None)


def _coordinates(message, prefix):
    lat = finite_number(message.get(prefix + "lat"))
    lon = finite_number(message.get(prefix + "long"))
    if lat is None or lon is None or lat == 0x7fffffff or lon == 0x7fffffff:
        return None
    lat, lon = lat * 180 / 2**31, lon * 180 / 2**31
    return (lat, lon) if abs(lat) <= 90 and abs(lon) <= 180 else None


def _weighted_average(points):
    """Trapezoidal time weighting; FIT records need not be one second apart."""
    if not points:
        return None
    area = duration = 0
    for (t1, v1), (t2, v2) in zip(points, points[1:]):
        if t2 > t1:
            area += (v1 + v2) / 2 * (t2 - t1)
            duration += t2 - t1
    return area / duration if duration else points[0][1]


def parse_garmin_fit(data: bytes):
    """Return metric form fields, a versioned profile, and missing-data notices."""
    if len(data) > MAX_FIT_BYTES:
        raise FitImportError("Choose a FIT file smaller than 10 MiB.")
    if len(data) < 14 or data[8:12] != b".FIT":
        raise FitImportError("This is not a FIT file. Export the dive as a FIT file from Garmin Dive.")
    try:
        # check_integrity consumes its stream; decoding must use a fresh one.
        if not Decoder(Stream.from_byte_array(data)).check_integrity():
            raise FitImportError("This FIT file is incomplete or damaged. Export it again from Garmin Dive.")
        messages, errors = Decoder(Stream.from_byte_array(data)).read(enable_crc_check=True)
    except FitImportError:
        raise
    except Exception as error:
        raise FitImportError("This FIT file could not be read. Export it again from Garmin Dive.") from error
    if errors:
        raise FitImportError("This FIT file is incomplete or damaged. Export it again from Garmin Dive.")

    file_ids = messages.get("file_id_mesgs", [])
    if len(file_ids) != 1 or file_ids[0].get("manufacturer") != "garmin":
        raise FitImportError("Choose a Garmin FIT file. Other dive computer brands are not supported yet.")
    if file_ids[0].get("type") != "activity":
        raise FitImportError("Choose a recorded dive activity, rather than a settings or course file.")
    sessions = messages.get("session_mesgs", [])
    if len(sessions) != 1:
        raise FitImportError("Import one dive at a time. This file does not contain exactly one dive session.")
    session = sessions[0]
    if session.get("sport") != "diving" or session.get("sub_sport") != "single_gas_diving":
        raise FitImportError("Only single-gas scuba dives are supported. Multi-gas, apnea, and closed-circuit dives cannot be imported yet.")

    gases = [gas for gas in messages.get("dive_gas_mesgs", []) if gas.get("status") != "disabled"]
    switches = {event.get("data") for event in messages.get("event_mesgs", [])
                if event.get("event") == "dive_gas_switched" and isinstance(event.get("data"), int)}
    if len(gases) > 1 or len(switches) > 1 or any(gas.get("mode", "open_circuit") != "open_circuit" for gas in gases):
        raise FitImportError("Only single-gas open-circuit dives are supported. This file contains multiple gases or a closed-circuit gas.")

    records = [record for record in messages.get("record_mesgs", []) if _utc(record.get("timestamp"))]
    records.sort(key=lambda record: _utc(record["timestamp"]))
    start = _utc(session.get("start_time")) or (_utc(records[0]["timestamp"]) if records else None)
    if start is None:
        raise FitImportError("This dive has no usable start time.")
    end = _utc(session.get("timestamp"))
    records = [record for record in records if _utc(record["timestamp"]) >= start
               and (end is None or _utc(record["timestamp"]) <= end)]
    profile = [{"elapsed_seconds": (_utc(record["timestamp"]) - start).total_seconds(), "depth_m": record["depth"]}
               for record in records if finite_number(record.get("depth"), 0) is not None]
    if len(profile) > MAX_PROFILE_POINTS:
        raise FitImportError("This dive has too many depth measurements to import. Choose a shorter single-dive export.")
    session_index = session.get("message_index", 0) & 0x0fff
    summaries = messages.get("dive_summary_mesgs", [])
    summary = next((item for item in summaries if item.get("reference_mesg") == "session"
                    and item.get("reference_index", 0) == session_index), {})
    # A single lap can stand in for a missing session summary; never combine duplicate summaries.
    if not summary and len(messages.get("lap_mesgs", [])) == 1:
        summary = next((item for item in summaries if item.get("reference_mesg") == "lap"), {})
    max_depth = _first_number(summary.get("max_depth"), session.get("max_depth"),
                              max((point["depth_m"] for point in profile), default=None))
    avg_depth = _first_number(summary.get("avg_depth"), session.get("avg_depth"),
                              _weighted_average([(point["elapsed_seconds"], point["depth_m"]) for point in profile]))
    record_duration = profile[-1]["elapsed_seconds"] if profile else None
    bottom_time = _first_number(summary.get("bottom_time"), session.get("total_timer_time"),
                               session.get("total_elapsed_time"), record_duration)
    if max_depth is None or bottom_time is None or bottom_time <= 0:
        raise FitImportError("This dive is missing usable depth or duration data.")
    recording_duration = max(value for value in [bottom_time, record_duration,
                             _first_number(session.get("total_elapsed_time"), session.get("total_timer_time"))]
                             if value is not None)
    fields = {"depth_m": max_depth, "duration_min": math.floor(bottom_time / 60 + 0.5)}
    if avg_depth is not None:
        fields["average_depth_m"] = avg_depth

    local_start = start
    for activity in messages.get("activity_mesgs", []):
        local_end, utc_end = finite_number(activity.get("local_timestamp")), _utc(activity.get("timestamp"))
        if local_end is not None and utc_end is not None:
            try:
                offset = FIT_EPOCH + timedelta(seconds=local_end) - utc_end
                if abs(offset.total_seconds()) <= 24 * 3600:
                    local_start = start + offset
                    break
            except (OverflowError, ValueError):
                pass
    fields["date"] = local_start.date().isoformat()
    notices = []
    if gases:
        oxygen = finite_number(gases[0].get("oxygen_content"), 0)
        helium = finite_number(gases[0].get("helium_content", 0), 0)
        if oxygen is not None and helium is not None and oxygen + helium <= 100:
            fields.update(oxygen_pct=int(oxygen), helium_pct=int(helium), nitrogen_pct=int(100 - oxygen - helium))
    if "oxygen_pct" not in fields:
        notices.append("Gas mix was not available; check the gas mix before saving.")

    water_temp = finite_number(session.get("avg_temperature"))
    if water_temp is None:
        water_temp = _weighted_average([((_utc(record["timestamp"]) - start).total_seconds(), record["temperature"])
                    for record in records if finite_number(record.get("temperature")) is not None
                    and (finite_number(record.get("depth"), 0) or 0) > 0])
    if water_temp is not None:
        fields["water_temp_c"] = water_temp
    else:
        notices.append("Water temperature was not available.")
    # Standard FIT temperature is the sensor's reading during the dive, not a separate air measurement.
    notices.append("No separate air temperature was recorded.")
    coordinates = _coordinates(session, "start_position_")
    if coordinates is None:
        coordinates = next((position for record in records if (position := _coordinates(record, "position_")) is not None), None)
    if coordinates is None:
        coordinates = _coordinates(session, "end_position_")
    if coordinates is not None:
        fields.update(latitude=coordinates[0], longitude=coordinates[1])
    else:
        notices.append("GPS coordinates were not available; choose the dive site manually.")
    if not profile:
        notices.append("No depth profile measurements were available.")
    computer_data = {"version": 1, "source": "garmin", "started_at": start.isoformat(),
                     "bottom_time_seconds": bottom_time, "recording_duration_seconds": recording_duration,
                     "depth_profile": profile}
    return {"fields": fields, "computer_data": computer_data, "notices": notices}


def validate_computer_data(data):
    """Validate and project browser-submitted data before storing it."""
    invalid = FitImportError("The imported depth profile is invalid. Import the FIT file again.")
    if not isinstance(data, dict) or data.get("version") != 1 or data.get("source") != "garmin":
        raise invalid
    try:
        start = _utc(datetime.fromisoformat(data["started_at"]))
    except (KeyError, TypeError, ValueError):
        raise invalid from None
    bottom = finite_number(data.get("bottom_time_seconds"), 0)
    duration = finite_number(data.get("recording_duration_seconds"), 0)
    points = data.get("depth_profile")
    if start is None or bottom is None or bottom <= 0 or duration is None or duration < bottom:
        raise invalid
    if not isinstance(points, list) or len(points) > MAX_PROFILE_POINTS:
        raise invalid
    profile, previous = [], -1
    for point in points:
        if not isinstance(point, dict):
            raise invalid
        elapsed = finite_number(point.get("elapsed_seconds"), 0)
        depth = finite_number(point.get("depth_m"), 0)
        if elapsed is None or depth is None or elapsed < previous or elapsed > duration:
            raise invalid
        profile.append({"elapsed_seconds": elapsed, "depth_m": depth})
        previous = elapsed
    return {"version": 1, "source": "garmin", "started_at": start.isoformat(),
            "bottom_time_seconds": bottom, "recording_duration_seconds": duration, "depth_profile": profile}


def nearest_dive_site(latitude, longitude, sites):
    """Minimize Cartesian chord distance across all valid catalog coordinates."""
    def vector(lat, lon):
        lat, lon = math.radians(lat), math.radians(lon)
        return math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)

    if finite_number(latitude) is None or finite_number(longitude) is None or abs(latitude) > 90 or abs(longitude) > 180:
        return None
    origin = vector(latitude, longitude)
    closest = None
    for row in sites:
        site = dict(row)
        lat, lon = finite_number(site.get("latitude")), finite_number(site.get("longitude"))
        if lat is None or lon is None or abs(lat) > 90 or abs(lon) > 180:
            continue
        distance = sum((a - b)**2 for a, b in zip(origin, vector(lat, lon)))
        key = distance, site["id"]
        if closest is None or key < closest[0]:
            closest = key, site
    if closest is None:
        return None
    return {**closest[1], "distance_m": math.sqrt(closest[0][0]) * 6_371_000}
