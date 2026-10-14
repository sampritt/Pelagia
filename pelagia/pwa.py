"""Public PWA resources with release-specific asset caches."""

import hashlib
import json
from pathlib import Path

from flask import Response, render_template, send_from_directory


def init_app(app):
    static = Path(app.static_folder)
    templates = Path(app.root_path) / "templates"
    assets = ("css/app.css", "js/app.js", "js/pwa.js")
    icons = ("pelagia-mark.svg", "icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png")
    worker = (static / "service-worker.js").read_text()
    digest = hashlib.sha256(worker.encode())
    digest.update(Path(__file__).read_bytes())
    for path in [*(static / asset for asset in assets),
                 *(static / "img" / icon for icon in icons),
                 static / "manifest.webmanifest", templates / "offline.html"]:
        digest.update(path.read_bytes())
    version = digest.hexdigest()[:16]
    app.jinja_env.globals["pwa_asset_version"] = version
    precache = ["/offline.html", "/manifest.webmanifest",
                *(f"/static/{asset}?v={version}" for asset in assets),
                *(f"/static/img/{icon}" for icon in icons)]
    source = worker.replace("__PELAGIA_CACHE_VERSION__", version).replace("__PELAGIA_PRECACHE__", json.dumps(precache))

    @app.get("/service-worker.js")
    def pwa_service_worker():
        return Response(source, mimetype="application/javascript", headers={
            "Cache-Control": "no-cache", "Service-Worker-Allowed": "/",
        })

    @app.get("/manifest.webmanifest")
    def pwa_manifest():
        return send_from_directory(app.static_folder, "manifest.webmanifest", mimetype="application/manifest+json", max_age=0)

    @app.get("/offline.html")
    def pwa_offline():
        # This page is cached across sessions: it must never contain account data.
        return Response(render_template("offline.html"), headers={"Cache-Control": "no-cache"})
