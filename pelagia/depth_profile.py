"""Small server-rendered depth charts; original measurements stay untouched."""

import json

from .garmin_fit import validate_computer_data


def depth_profile_chart(db, dive_id):
    row = db.execute("SELECT data_json FROM dive_computer_data WHERE dive_id = ?", (dive_id,)).fetchone()
    if row is None:
        return None
    try:
        data = validate_computer_data(json.loads(row["data_json"]))
    except (ValueError, TypeError, RecursionError):
        return None
    points = data["depth_profile"]
    if len(points) < 2 or points[-1]["elapsed_seconds"] <= points[0]["elapsed_seconds"]:
        return None
    duration = data["recording_duration_seconds"]
    max_depth = max(point["depth_m"] for point in points)
    # Keep both extremes in each time bucket, including short depth excursions.
    # Bound SVG size even for a 100,000-sample recording.
    buckets = {}
    for index, point in enumerate(points):
        bucket = min(599, int(point["elapsed_seconds"] / duration * 600))
        if bucket not in buckets:
            buckets[bucket] = [index, index]
        else:
            low, high = buckets[bucket]
            if point["depth_m"] < points[low]["depth_m"]:
                buckets[bucket][0] = index
            if point["depth_m"] > points[high]["depth_m"]:
                buckets[bucket][1] = index
    indices = sorted({0, len(points) - 1, *(index for pair in buckets.values() for index in pair)})
    coordinates = [(44 + points[i]["elapsed_seconds"] / duration * 716,
                    28 + points[i]["depth_m"] / (max_depth or 1) * 222) for i in indices]
    line = "M " + " L ".join(f"{x:.2f},{y:.2f}" for x, y in coordinates)
    return {"line": line,
            "fill": f"{line} L {coordinates[-1][0]:.2f},28 L {coordinates[0][0]:.2f},28 Z",
            "max_depth_m": max_depth, "duration_minutes": round(duration / 60, 1)}
