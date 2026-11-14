"""Stable fin-brand URLs, independent of caches for the retired wave artwork."""

from functools import lru_cache
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from flask import abort, send_file
from PIL import Image

from .sharing import _brand_lockup


ASSETS = {
    "fin-mark.png": "pelagia-mark.png",
    "fin-icon-192.png": "icon-192.png",
    "fin-icon-512.png": "icon-512.png",
    "fin-icon-maskable-512.png": "icon-maskable-512.png",
    "fin-touch-icon.png": "apple-touch-icon.png",
}
PREVIEW_FILENAME = "pelagia-fin-preview.png"


@lru_cache(maxsize=1)
def preview_bytes():
    # Reuse the supplied fin and wordmark without redrawing either outline.
    image = Image.new("RGBA", (1200, 630), "#0666bd")
    logo = _brand_lockup()
    width = 560
    logo = logo.resize((width, round(width * logo.height / logo.width)), Image.Resampling.LANCZOS)
    image.alpha_composite(logo, ((image.width - logo.width) // 2, (image.height - logo.height) // 2))
    stream = BytesIO()
    image.convert("RGB").save(stream, "PNG")
    return stream.getvalue()


@lru_cache(maxsize=1)
def favicon_bytes():
    stream = BytesIO()
    with Image.open(Path(__file__).parent / "static/img/icon-512.png") as source:
        source.save(stream, "ICO", sizes=[(size, size) for size in (16, 32, 48, 64, 128, 256)])
    return stream.getvalue()


def init_app(app):
    @app.get("/brand/<filename>")
    def brand_asset(filename):
        if filename == PREVIEW_FILENAME:
            data = preview_bytes()
            return send_file(BytesIO(data), mimetype="image/png", max_age=0,
                             download_name=filename, etag=sha256(data).hexdigest())
        asset = ASSETS.get(filename)
        if asset is None:
            abort(404)
        return send_file(Path(app.static_folder) / "img" / asset, max_age=0)

    @app.get("/favicon.ico")
    def favicon():
        data = favicon_bytes()
        return send_file(BytesIO(data), mimetype="image/vnd.microsoft.icon", max_age=0,
                         download_name="favicon.ico", etag=sha256(data).hexdigest())
