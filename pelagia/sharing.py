"""A deliberately limited public view and its social preview artwork."""

from io import BytesIO
from datetime import date
from functools import lru_cache
from pathlib import Path

from flask import current_app
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from .db import get_db
from .metrics import format_metric
from .units import display_measurement
from .dive_options import dive_type_options
from .static_maps import render_static_map


def fetch_public_dive(dive_id):
    # Do not fetch private fields and then hide them with CSS. Guests get only
    # this allowlist, including no buddy, email, notes, species or comments.
    row = get_db().execute(
        """
        SELECT d.id, d.site_name, d.country_or_area, d.date, d.latitude,
               d.longitude, d.depth_m, d.average_depth_m, d.duration_min, d.dive_type, d.dive_types_json,
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
    dive["dive_types"] = dive_type_options(dive)
    dive["photos"] = get_db().execute(
        "SELECT filename FROM photos WHERE dive_id = ? ORDER BY id", (dive_id,),
    ).fetchall()
    return dive


def fetch_public_dive_site(site_id):
    row = get_db().execute(
        """
        SELECT ds.id, ds.name, ds.country_or_area, ds.latitude, ds.longitude,
               (SELECT COUNT(*) FROM dive_site_likes WHERE dive_site_id = ds.id) AS like_count
        FROM dive_sites ds WHERE ds.id = ?
        """, (site_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def share_description(dive):
    location = f" in {dive['country_or_area']}" if dive["country_or_area"] else ""
    average_depth = dive.get("average_depth_m")
    average = f" · {format_metric(average_depth)} m average depth" if average_depth is not None else ""
    return f"{dive['site_name']}{location} · {format_metric(dive['depth_m'])} m deep{average} · {dive['duration_min']} min underwater. Explore this dive on Pelagia."


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
    with Image.open(Path(__file__).parent / "static" / "img" / "pelagia-mark.png") as logo:
        return logo.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)


@lru_cache(maxsize=1)
def _brand_lockup():
    # Keep the supplied fin and wordmark outlines exactly. The source has a
    # blue background (low red) and white artwork (high red), so its red channel
    # provides a clean alpha mask, including the counters inside the letters.
    with Image.open(Path(__file__).parent / "static" / "img" / "pelagia-lockup-source.png") as source:
        alpha = source.convert("RGB").getchannel("R").point(
            lambda value: max(0, min(255, round((value - 32) * 255 / 213)))
        )
    logo = Image.new("RGBA", alpha.size, "white")
    logo.putalpha(alpha)
    return logo.crop(alpha.getbbox())


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


def render_transparent_share_image(dive, *, length_unit="m"):
    """A white site/stats/brand overlay with real transparency and no media."""
    image = Image.new("RGBA", (1200, 630), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    title_font, lines, step, height = _layout_title(draw, dive["site_name"], width=1000, height=152)
    title_top = round(153 - height / 2)
    for index, line in enumerate(lines):
        draw.text((600, title_top + index * step), line, font=title_font,
                  fill="white", anchor="mt")

    depth = format_metric(display_measurement(dive["depth_m"], length_unit))
    duration = format_metric(dive["duration_min"])
    for center, value, label in ((430, f"{depth} {length_unit}", "MAX DEPTH"),
                                 (770, f"{duration} min", "DIVE TIME")):
        draw.text((center, 278), value, font=_font(56, bold=True), fill="white", anchor="mt")
        draw.text((center, 349), label, font=_font(18), fill="white", anchor="mt")

    logo = _brand_lockup()
    logo = logo.resize((280, round(280 * logo.height / logo.width)), Image.Resampling.LANCZOS)
    image.alpha_composite(logo, ((image.width - logo.width) // 2, 414))
    stream = BytesIO()
    image.save(stream, "PNG")
    stream.seek(0)
    return stream


def render_share_image(dive, *, length_unit="m"):
    image = Image.new("RGB", (1200, 630), "#062a46")
    # Gallery order determines the primary photo. The site map replaces the
    # ocean artwork when no readable photo is attached and coordinates exist.
    uploads = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    media = None
    for photo in dive["photos"]:
        candidate = (uploads / photo["filename"].removeprefix("uploads/")).resolve()
        if not candidate.is_relative_to(uploads) or not candidate.is_file():
            continue
        try:
            with Image.open(candidate) as photo:
                media = ImageOps.fit(ImageOps.exif_transpose(photo).convert("RGB"), (580, 630))
            break
        except (OSError, UnidentifiedImageError):
            continue
    if media is None:
        media = render_static_map(dive["latitude"], dive["longitude"])
    if media is None:
        try:
            with Image.open(Path(current_app.static_folder, "img/ocean-hero-v2.jpg")) as artwork:
                media = ImageOps.fit(artwork.convert("RGB"), (580, 630))
        except (OSError, UnidentifiedImageError):
            pass
    if media is not None:
        image.paste(media, (620, 0))
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
    metrics = ((56, display_measurement(dive["depth_m"], length_unit), length_unit, "MAX DEPTH"),
               (303, dive["duration_min"], "min", "DURATION"))
    if dive.get("average_depth_m") is not None:
        metric_font, unit_font = _font(44, bold=True), _font(20)
        metrics = ((56, display_measurement(dive["depth_m"], length_unit), length_unit, "MAX DEPTH"),
                   (245, display_measurement(dive["average_depth_m"], length_unit), length_unit, "AVG DEPTH"),
                   (435, dive["duration_min"], "min", "DURATION"))
    for x, value, unit, label in metrics:
        value = format_metric(value)
        draw.text((x, 477), value, font=metric_font, fill="white", anchor="ls")
        draw.text((x + draw.textlength(value, font=metric_font) + 9, 477), unit, font=unit_font, fill="#61caff", anchor="ls")
        draw.text((x, 497), label, font=_font(16), fill="#b7d1e1", anchor="lt")
    footer = f"Logged by {dive['username']}  ·  {_display_date(dive['date'])}"
    draw.text((56, 571), _fit_line(draw, footer, _font(24), 540), font=_font(24), fill="#b7d1e1", anchor="ls")
    stream = BytesIO()
    image.save(stream, "JPEG", quality=88)
    stream.seek(0)
    return stream
