"""Render the dive's OpenStreetMap viewport into shareable artwork."""

import hashlib
import json
import math
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import requests
from flask import current_app
from PIL import Image, ImageDraw, UnidentifiedImageError


TILE_SIZE = 256
MAP_ZOOM = 10  # Match the logged dive's map view.
CACHE_SECONDS = 7 * 24 * 60 * 60
DEFAULT_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"


def _atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(content)
        temporary_path = Path(temporary.name)
    try:
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _decode_tile(content):
    with Image.open(BytesIO(content)) as image:
        if image.size != (TILE_SIZE, TILE_SIZE):
            raise ValueError("Unexpected map tile size")
        return image.convert("RGB")


def _load_tile(url, cache_dir, headers):
    key = hashlib.sha256(url.encode()).hexdigest()
    cached_path = cache_dir / f"{key}.png"
    metadata_path = cache_dir / f"{key}.json"
    cached, metadata = None, {}
    try:
        cached = _decode_tile(cached_path.read_bytes())
        metadata = json.loads(metadata_path.read_text())
    except (OSError, ValueError, UnidentifiedImageError):
        pass
    if cached is not None and metadata.get("expires", 0) > time.time():
        return cached
    request_headers = dict(headers)
    if cached is not None:
        for field, header in (("etag", "If-None-Match"), ("last_modified", "If-Modified-Since")):
            if metadata.get(field):
                request_headers[header] = metadata[field]
    try:
        with requests.get(url, headers=request_headers, timeout=(2, 3)) as response:
            if response.status_code == 304 and cached is not None:
                tile = cached
            else:
                response.raise_for_status()
                tile = _decode_tile(response.content)
            max_age = CACHE_SECONDS
            for directive in response.headers.get("Cache-Control", "").split(","):
                name, _, value = directive.strip().partition("=")
                if name.lower() == "max-age" and value.strip('"').isdigit():
                    max_age = max(max_age, int(value.strip('"')))
            metadata.update(expires=time.time() + max_age)
            for field, header in (("etag", "ETag"), ("last_modified", "Last-Modified")):
                if response.headers.get(header):
                    metadata[field] = response.headers[header]
            try:
                if response.status_code != 304:
                    _atomic_write(cached_path, response.content)
                _atomic_write(metadata_path, json.dumps(metadata).encode())
            except OSError:
                # A cache write failure must not prevent a share from rendering.
                pass
            return tile
    except (requests.RequestException, OSError, ValueError, UnidentifiedImageError):
        # A previously rendered tile still provides useful context during outages.
        return cached


def render_static_map(latitude, longitude, size=(580, 630), *, pin_position=None):
    try:
        latitude, longitude = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(latitude) and math.isfinite(longitude)
            and -85 <= latitude <= 85 and -180 <= longitude <= 180):
        return None

    width, height = size
    pin_x, pin_y = pin_position if pin_position is not None else (width // 2, height // 2)
    world_size = TILE_SIZE * 2 ** MAP_ZOOM
    sin_latitude = math.sin(math.radians(latitude))
    center_x = (longitude + 180) / 360 * world_size
    center_y = (0.5 - math.log((1 + sin_latitude) / (1 - sin_latitude)) / (4 * math.pi)) * world_size
    origin_x, origin_y = round(center_x - pin_x), round(center_y - pin_y)
    tile_count = 2 ** MAP_ZOOM
    positions = [
        (x, y)
        for y in range(max(0, origin_y // TILE_SIZE), min(tile_count - 1, (origin_y + height - 1) // TILE_SIZE) + 1)
        for x in range(origin_x // TILE_SIZE, (origin_x + width - 1) // TILE_SIZE + 1)
    ]
    tile_url = current_app.config.get("MAP_TILE_URL", DEFAULT_TILE_URL)
    cache_dir = Path(current_app.config.get("MAP_TILE_CACHE_DIR") or Path(current_app.config["DATABASE"]).parent / "map_tiles")
    headers = {"User-Agent": "Pelagia/1.0 (dive share maps)"}
    if current_app.config.get("PUBLIC_BASE_URL"):
        headers["Referer"] = current_app.config["PUBLIC_BASE_URL"] + "/"
    # Fetch only this visible viewport, with bounded concurrency and timeouts.
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_load_tile, tile_url.format(z=MAP_ZOOM, x=x % tile_count, y=y), cache_dir, headers)
                   for x, y in positions]
        tiles = [future.result() for future in futures]
    if any(tile is None for tile in tiles):
        return None
    image = Image.new("RGB", size, "#aad3df")
    for (x, y), tile in zip(positions, tiles):
        image.paste(tile, (x * TILE_SIZE - origin_x, y * TILE_SIZE - origin_y))
    draw = ImageDraw.Draw(image)
    x, y = pin_x, pin_y
    draw.ellipse((x - 22, y - 22, x + 22, y + 22), fill="#61caff", outline="white", width=4)
    draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill="#062a46")
    return image
