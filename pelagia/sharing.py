"""A deliberately limited public view and its social preview artwork."""

from io import BytesIO
from pathlib import Path

from flask import current_app
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from .db import get_db


def fetch_public_dive(dive_id):
    # Do not fetch private fields and then hide them with CSS. Guests get only
    # this allowlist, including no buddy, email, notes, species or comments.
    row = get_db().execute(
        """
        SELECT d.id, d.site_name, d.country_or_area, d.date, d.latitude,
               d.longitude, d.depth_m, d.duration_min, d.dive_type,
               COALESCE(dc.name, d.dive_center_name) AS center_name,
               u.username, u.profile_photo
        FROM dives d JOIN users u ON u.id = d.user_id
        LEFT JOIN dive_centers dc ON dc.id = d.dive_center_id
        WHERE d.id = ? AND COALESCE(d.is_deleted, 0) = 0
        """, (dive_id,),
    ).fetchone()
    if row is None:
        return None
    dive = dict(row)
    dive["photos"] = get_db().execute(
        "SELECT filename FROM photos WHERE dive_id = ? ORDER BY id", (dive_id,),
    ).fetchall()
    return dive


def share_description(dive):
    location = f" in {dive['country_or_area']}" if dive["country_or_area"] else ""
    return f"{dive['site_name']}{location} · {dive['depth_m']} m deep · {dive['duration_min']} min underwater. Explore this dive on Pelagia."


def _font(size):
    for name in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ):
        if Path(name).is_file():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default(size=size)


def _fit_line(draw, text, font, width):
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def render_share_image(dive):
    image = Image.new("RGB", (1200, 630), "#062a46")
    # Use an existing dive photo, or the app's ocean artwork when there are none.
    artwork = Path(current_app.static_folder, "img/ocean-hero-v2.jpg")
    if dive["photos"]:
        uploads = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
        candidate = (uploads / dive["photos"][0]["filename"]).resolve()
        if candidate.is_relative_to(uploads) and candidate.is_file():
            artwork = candidate
    try:
        with Image.open(artwork) as photo:
            image.paste(ImageOps.fit(ImageOps.exif_transpose(photo).convert("RGB"), (580, 630)), (620, 0))
    except (OSError, UnidentifiedImageError):
        pass
    draw = ImageDraw.Draw(image)
    # A quiet blue gradient joins the photograph to the text panel.
    overlay = Image.new("RGBA", image.size)
    overlay_draw = ImageDraw.Draw(overlay)
    for x in range(620, 950):
        overlay_draw.line((x, 0, x, 630), fill=(6, 42, 70, round(255 * (950 - x) / 330)))
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(image)
    for y in (62, 75):
        draw.line([(56, y), (66, y - 5), (78, y + 5), (90, y - 5), (102, y)], fill="#61caff", width=4)
    draw.text((119, 48), "Pelagia", font=_font(29), fill="white")
    draw.text((56, 137), "CHECK OUT MY LOGGED DIVE", font=_font(16), fill="#61caff")
    title_font = _font(51)
    words = dive["site_name"].split()
    lines, line = [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if line and draw.textlength(trial, font=title_font) > 550:
            lines.append(line)
            line = word
        else:
            line = trial
    lines.append(line)
    for index, line in enumerate(lines[:2]):
        if index == 1 and len(lines) > 2:
            line += "…"
        draw.text((54, 183 + index * 62), _fit_line(draw, line, title_font, 550), font=title_font, fill="white")
    draw.text((56, 329), _fit_line(draw, dive["country_or_area"] or "Dive log", _font(24), 540), font=_font(24), fill="#b7d1e1")
    draw.line((56, 396, 555, 396), fill="#31546e", width=1)
    for x, value, label in ((56, f"{dive['depth_m']} m", "DEPTH"), (303, f"{dive['duration_min']} min", "DURATION")):
        draw.text((x, 425), value, font=_font(43), fill="white")
        draw.text((x, 483), label, font=_font(14), fill="#61caff")
    footer = f"Logged by {dive['username']}  ·  {dive['date']}"
    draw.text((56, 558), _fit_line(draw, footer, _font(18), 540), font=_font(18), fill="#b7d1e1")
    stream = BytesIO()
    image.save(stream, "JPEG", quality=88)
    stream.seek(0)
    return stream
