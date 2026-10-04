"""A deliberately limited public view and its social preview artwork."""

from io import BytesIO
from datetime import date
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


def _font(size, bold=False):
    names = (
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf")
        if bold else
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf")
    )
    for name in names:
        if Path(name).is_file():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default(size=size)


def _brand_mark(size=52):
    # Rasterize the same rounded square and cubic waves as pelagia-mark.svg.
    # Supersampling keeps the small mark crisp without another dependency.
    pixels = size * 4
    scale = pixels / 64
    mark = Image.new("RGBA", (pixels, pixels))
    draw = ImageDraw.Draw(mark)
    for y in range(pixels):
        progress = y / (pixels - 1)
        color = tuple(round(start + (end - start) * progress) for start, end in zip((21, 151, 255), (7, 86, 216)))
        draw.line((0, y, pixels, y), fill=color)
    for baseline in (25, 39):
        points = []
        for segment in range(4):
            x = 5 + segment * 14
            start_y = baseline if segment % 2 == 0 else baseline - 7
            end_y = baseline - 7 if segment % 2 == 0 else baseline
            for step in range(17):
                t = step / 16
                px = (1-t)**3 * x + 3*(1-t)**2*t*(x+7) + 3*(1-t)*t**2*(x+7) + t**3*(x+14)
                py = (1-t)**3 * start_y + 3*(1-t)**2*t*start_y + 3*(1-t)*t**2*end_y + t**3*end_y
                points.append((px * scale, py * scale))
        draw.line(points, fill="white", width=round(5 * scale), joint="curve")
        radius = 2.5 * scale
        for x, y in (points[0], points[-1]):
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill="white")
    mask = Image.new("L", mark.size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, pixels-1, pixels-1), radius=18 * scale, fill=255)
    mark.putalpha(mask)
    return mark.resize((size, size), Image.Resampling.LANCZOS)


def _fit_line(draw, text, font, width):
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def _layout_title(draw, title, width=550, height=160):
    words = title.split() or ["Dive log"]
    # Keep the established headline size when it fits, then shrink to fit the
    # entire name. Exceptionally long single words can wrap within the word.
    for size in range(68, 0, -1):
        font = _font(size, bold=True)
        if size >= 24 and any(draw.textlength(word, font=font) > width for word in words):
            continue
        lines, line = [], ""
        for word in words:
            trial = f"{line} {word}".strip()
            if draw.textlength(trial, font=font) <= width:
                line = trial
                continue
            if line:
                lines.append(line)
            line = ""
            for character in word:
                if line and draw.textlength(line + character, font=font) > width:
                    lines.append(line)
                    line = ""
                line += character
        lines.append(line)
        step = size + max(2, round(size * 0.15))
        block_height = max(
            index * step + draw.textbbox((0, 0), line, font=font, anchor="lt")[3]
            for index, line in enumerate(lines)
        )
        if block_height <= height:
            return font, lines, step, block_height
    return font, lines, step, block_height


def _draw_caption(draw, position, text):
    font = _font(16)
    x, y = position
    for character in text:
        draw.text((x, y), character, font=font, fill="#61caff")
        x += draw.textlength(character, font=font) + 1.5


def _display_date(value):
    try:
        logged_on = date.fromisoformat(value)
    except (TypeError, ValueError):
        return value
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"{months[logged_on.month - 1]} {logged_on.day}, {logged_on.year}"


def render_share_image(dive):
    image = Image.new("RGB", (1200, 630), "#062a46")
    # Gallery order determines the primary photo. Skip unavailable uploads and
    # fall back to the app's ocean artwork if no photo can be read.
    uploads = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    artwork = []
    for photo in dive["photos"]:
        candidate = (uploads / photo["filename"].removeprefix("uploads/")).resolve()
        if candidate.is_relative_to(uploads) and candidate.is_file():
            artwork.append(candidate)
    artwork.append(Path(current_app.static_folder, "img/ocean-hero-v2.jpg"))
    for candidate in artwork:
        try:
            with Image.open(candidate) as photo:
                image.paste(ImageOps.fit(ImageOps.exif_transpose(photo).convert("RGB"), (580, 630)), (620, 0))
            break
        except (OSError, UnidentifiedImageError):
            continue
    # A quiet blue gradient joins the photograph to the text panel.
    overlay = Image.new("RGBA", image.size)
    overlay_draw = ImageDraw.Draw(overlay)
    for x in range(620, 950):
        overlay_draw.line((x, 0, x, 630), fill=(6, 42, 70, round(255 * (950 - x) / 330)))
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    mark = _brand_mark()
    image.paste(mark, (56, 48), mark)
    draw = ImageDraw.Draw(image)
    draw.text((124, 57), "Pelagia", font=_font(34, bold=True), fill="white", anchor="lt")
    title_font, lines, title_step, title_height = _layout_title(draw, dive["site_name"])
    title_top = round(237 - title_height / 2) if len(lines) > 1 else 197
    _draw_caption(draw, (56, title_top - 46), "LOGGED DIVE")
    for index, line in enumerate(lines):
        draw.text((54, title_top + index * title_step), line, font=title_font, fill="white", anchor="lt")
    location_top = title_top + title_height + 22
    location_font = _font(28)
    draw.text((56, location_top), _fit_line(draw, dive["country_or_area"] or "Dive log", location_font, 540), font=location_font, fill="#b7d1e1", anchor="lt")
    draw.line((56, 396, 555, 396), fill="#31546e", width=1)
    metric_font, unit_font = _font(56, bold=True), _font(26)
    for x, value, unit, label in ((56, dive["depth_m"], "m", "DEPTH"), (303, dive["duration_min"], "min", "DURATION")):
        value = str(value)
        draw.text((x, 477), value, font=metric_font, fill="white", anchor="ls")
        draw.text((x + draw.textlength(value, font=metric_font) + 9, 477), unit, font=unit_font, fill="#61caff", anchor="ls")
        draw.text((x, 497), label, font=_font(20), fill="#b7d1e1", anchor="lt")
    footer = f"Logged by {dive['username']}  ·  {_display_date(dive['date'])}"
    draw.text((56, 571), _fit_line(draw, footer, _font(24), 540), font=_font(24), fill="#b7d1e1", anchor="ls")
    stream = BytesIO()
    image.save(stream, "JPEG", quality=88)
    stream.seek(0)
    return stream
