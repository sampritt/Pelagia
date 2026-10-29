"""A deliberately limited public view and its social preview artwork."""

from io import BytesIO
import math
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

from flask import current_app
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, UnidentifiedImageError

from .db import get_db
from .metrics import format_metric
from .units import display_measurement
from .dive_options import dive_type_options, gas_mix_label
from .static_maps import render_static_map


def fetch_public_dive(dive_id):
    # Do not fetch private fields and then hide them with CSS. Guests get only
    # this allowlist, including no buddy, email, notes, species or comments.
    row = get_db().execute(
        """
        SELECT d.id, d.site_name, d.country_or_area, d.date, d.latitude,
               d.longitude, d.depth_m, d.average_depth_m, d.duration_min, d.dive_type, d.dive_types_json,
               d.oxygen_pct, d.helium_pct, d.sac_rate_l_min, d.weight_kg, d.exposure,
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
    dive["gas_mix_label"] = (
        gas_mix_label(dive["oxygen_pct"], dive["helium_pct"])
        if dive["oxygen_pct"] is not None and dive["helium_pct"] is not None else None
    )
    dive["dive_types"] = dive_type_options(dive)
    dive["photos"] = get_db().execute(
        "SELECT filename FROM photos WHERE dive_id = ? ORDER BY id", (dive_id,),
    ).fetchall()
    return dive


def fetch_public_dive_site(site_id):
    row = get_db().execute(
        """
        SELECT ds.id, ds.name, ds.country_or_area, ds.latitude, ds.longitude
        FROM dive_sites ds WHERE ds.id = ?
        """, (site_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def fetch_public_dive_center(center_id):
    row = get_db().execute(
        """
        SELECT dc.id, dc.name, dc.physical_address, dc.location, dc.website,
               (SELECT COUNT(*) FROM dive_center_likes WHERE dive_center_id = dc.id) AS like_count
        FROM dive_centers dc WHERE dc.id = ?
        """, (center_id,),
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
    title_words = title.split() or ["Dive log"]
    alias = re.fullmatch(r"(.+?)\s+(\([^()]+\))", title.strip())
    # Keep the established headline size when it fits, then shrink to fit the
    # entire name. Exceptionally long single words can wrap within the word.
    for size in range(68, 0, -1):
        font = _font(size, bold=True)
        # An alternate site name reads best as one phrase. Keep it together
        # when it fits a line; exceptionally long aliases can still wrap.
        words = (alias[1].split() + [alias[2]]
                 if alias and draw.textlength(alias[2], font=font) <= width else title_words)
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


def _display_date(value):
    try:
        logged_on = date.fromisoformat(value)
    except (TypeError, ValueError):
        return value
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"{months[logged_on.month - 1]} {logged_on.day}, {logged_on.year}"


def _select_share_stats(dive, *, length_unit="m", weight_unit="kg", map_only=False):
    """Choose the first four recorded values in the shared display priority."""
    stats = []

    def measurement(key, unit, label, *, weight=False):
        value = dive.get(key)
        if value is not None and value != "" and math.isfinite(float(value)) and float(value) >= 0:
            stats.append((format_metric(display_measurement(value, unit), weight=weight), unit, label))

    measurement("depth_m", length_unit, "MAX DEPTH")
    if not map_only:
        measurement("average_depth_m", length_unit, "AVG DEPTH")
    measurement("duration_min", "min", "DIVE TIME")
    if map_only:
        return stats
    if dive.get("gas_mix_label"):
        stats.append((dive["gas_mix_label"], "", "GAS MIX"))
    measurement("sac_rate_l_min", "L/min", "SAC RATE")
    measurement("weight_kg", weight_unit, "WEIGHT", weight=True)
    exposure = str(dive.get("exposure") or "").strip()
    if exposure and exposure.lower() not in {"none", "-"}:
        stats.append((exposure, "", "EXPOSURE"))
    return stats[:4]


def _draw_stat(draw, x, baseline, value, unit, label, *, width, size=68,
               unit_size=28, centered=False, transparent=False):
    """Keep units secondary and fit each metric within its own column."""
    unit_font = _font(unit_size)
    unit_width = draw.textlength(unit, font=unit_font) + 9 if unit else 0
    while size > 12:
        font = _font(size, bold=True)
        value_width = draw.textlength(value, font=font)
        if value_width + unit_width <= width:
            break
        size -= 1
    left = x - (value_width + unit_width) / 2 if centered else x
    draw.text((left, baseline), value, font=font, fill="white", anchor="ls")
    if unit:
        draw.text((left + value_width + 9, baseline), unit, font=unit_font,
                  fill="white" if transparent else "#a9ddd8", anchor="ls")
    draw.text((x, baseline + 24), label, font=_font(24),
              fill="white" if transparent else "#b8cecf",
              anchor="mt" if centered else "lt")


def _place_lockup(image, width, x, y):
    logo = _brand_lockup()
    logo = logo.resize((width, round(width * logo.height / logo.width)), Image.Resampling.LANCZOS)
    image.alpha_composite(logo, (x, y))


TRANSPARENT_LAYOUTS = {
    "vertical": (720, 1280),
    "horizontal": (1600, 600),
    "stacked": (1200, 780),
    "map": (960, 1200),
    "depth_profile": (960, 1200),
}


def _draw_share_title(draw, title, center, middle, width, height=152):
    font, lines, step, block_height = _layout_title(draw, title, width=width, height=height)
    top = round(middle - block_height / 2)
    for index, line in enumerate(lines):
        draw.text((center, top + index * step), line, font=font, fill="white", anchor="mt")


def _equal_stat_size(draw, stats, width, unit_size=32, max_size=80):
    # Fit the longest value once, then give every stat the same type size.
    for size in range(max_size, 11, -1):
        font, unit_font = _font(size, bold=True), _font(unit_size)
        if all(draw.textlength(value, font=font)
               + (draw.textlength(unit, font=unit_font) + 9 if unit else 0) <= width
               for value, unit, _ in stats):
            return size
    return size


def _draw_share_depth_profile(image, chart, length_unit):
    """Outline only: keep the chart interior transparent for photo overlays."""
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = 170, 310, 830, 690
    for y in (top, (top + bottom) / 2, bottom):
        draw.line((left, y, right, y), fill=(255, 255, 255, 70), width=1)
    # Supersample the trace so shallow slopes remain smooth in the PNG.
    trace = Image.new("RGBA", (1520, 1000))
    points = [((left - 100 + (x - 44) / 716 * (right - left)) * 2,
               (top - 260 + (y - 28) / 222 * (bottom - top)) * 2)
              for x, y in chart["coordinates"]]
    ImageDraw.Draw(trace).line(points, fill="white", width=8, joint="curve")
    image.alpha_composite(trace.resize((760, 500), Image.Resampling.LANCZOS), (100, 260))
    font = _font(24)
    draw.text((left - 18, top), "0", font=font, fill="white", anchor="rm")
    draw.text((left - 18, bottom),
              format_metric(display_measurement(chart["max_depth_m"], length_unit)),
              font=font, fill="white", anchor="rm")
    draw.text((left, top - 28), length_unit, font=font, fill="white", anchor="ls")
    draw.text((left, bottom + 24), "0 min", font=font, fill="white", anchor="lt")
    draw.text((right, bottom + 24), f'{chart["duration_minutes"]:.0f} min',
              font=font, fill="white", anchor="rt")


def render_transparent_share_image(dive, *, length_unit="m", weight_unit="kg", layout="stacked"):
    """Transparent overlays with equal stat emphasis and distinct compositions."""
    image = Image.new("RGBA", TRANSPARENT_LAYOUTS[layout], (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    stats = _select_share_stats(dive, length_unit=length_unit, weight_unit=weight_unit, map_only=layout in {"map", "depth_profile"})
    count = len(stats)

    if layout == "vertical":
        _place_lockup(image, 190, 265, 55)
        baselines = {0: (), 1: (700,), 2: (520, 900), 3: (430, 720, 1010), 4: (365, 610, 855, 1100)}[count]
        positions = [(360, baseline) for baseline in baselines]
        column_width = 600
    elif layout == "horizontal":
        column_width = 1480 / max(1, count) - 36
        positions = [(60 + (index + 0.5) * 1480 / count, 220) for index in range(count)]
        _place_lockup(image, 190, 705, 340)
    elif layout in {"map", "depth_profile"}:
        _draw_share_title(draw, dive["site_name"], 480, 130, 800, height=160)
        if layout == "depth_profile":
            _draw_share_depth_profile(image, dive["depth_chart"], length_unit)
        else:
            map_image = render_static_map(dive["latitude"], dive["longitude"], size=(760, 500))
            if map_image is not None:
                mask = Image.new("L", (3040, 2000))
                ImageDraw.Draw(mask).rounded_rectangle((0, 0, 3039, 1999), radius=128, fill=255)
                map_image = map_image.convert("RGBA")
                map_image.putalpha(mask.resize((760, 500), Image.Resampling.LANCZOS))
                image.alpha_composite(map_image, (100, 260))
            else:
                draw.rounded_rectangle((100, 260, 859, 759), radius=32, outline="#b8cecf", width=2)
                draw.text((480, 510), "Map unavailable", font=_font(30), fill="white", anchor="mm")
        positions = [(480, 890)] if count == 1 else [(280, 890), (680, 890)]
        column_width = 330
        _place_lockup(image, 190, 385, 1020)
    else:
        _draw_share_title(draw, dive["site_name"], 600, 123, 1000)
        first_row = 310 if count > 2 else 380
        positions = [(600, first_row)] if count == 1 else [(340, first_row), (860, first_row)]
        if count == 3:
            positions.append((600, 500))
        elif count == 4:
            positions.extend(((340, 500), (860, 500)))
        column_width = 470
        _place_lockup(image, 190, 505, 594 if count > 2 else 560)

    size = _equal_stat_size(draw, stats, column_width)
    for (x, baseline), (value, unit, label) in zip(positions, stats):
        _draw_stat(draw, x, baseline, value, unit, label, width=column_width,
                   size=size, unit_size=32, centered=True, transparent=True)

    # Local shadows support footage without filling the transparent canvas.
    shadow = Image.new("RGBA", image.size, (4, 23, 30, 0))
    shadow_alpha = image.getchannel("A").filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(2))
    shadow.putalpha(shadow_alpha.point(lambda a: round(a * 0.6)))
    image = Image.alpha_composite(shadow, image)
    stream = BytesIO()
    image.save(stream, "PNG")
    stream.seek(0)
    return stream


@lru_cache(maxsize=1)
def _share_scrim():
    # Smooth, continuous shading replaces the split text/media panels. The
    # upper-right stays open for the site's location pin.
    width, height = 1200, 630
    horizontal = []
    for x in range(width):
        progress = min(1, max(0, (x - 180) / 900))
        horizontal.append(0.94 * (1 - progress * progress * (3 - 2 * progress)))
    pixels = bytearray()
    for y in range(height):
        top = 0.16 * max(0, 1 - y / 160)
        progress = min(1, max(0, (y - 290) / 260))
        bottom = 0.96 * progress * progress * (3 - 2 * progress)
        for left in horizontal:
            alpha = 1 - (1 - left) * (1 - bottom) * (1 - top)
            pixels.extend((5, 26, 34, round(255 * alpha)))
    return Image.frombytes("RGBA", (width, height), bytes(pixels))


def render_share_image(dive, *, length_unit="m", weight_unit="kg"):
    # Every splash uses the full-bleed map, with the pin clear of the headline.
    media = render_static_map(dive["latitude"], dive["longitude"],
                              size=(1200, 630), pin_position=(930, 235))
    if media is None:
        try:
            with Image.open(Path(current_app.static_folder, "img/ocean-hero-v2.jpg")) as artwork:
                media = ImageOps.fit(artwork.convert("RGB"), (1200, 630))
        except (OSError, UnidentifiedImageError):
            media = Image.new("RGB", (1200, 630), "#123f4b")
    image = Image.alpha_composite(media.convert("RGBA"), _share_scrim())
    _place_lockup(image, 145, 56, 39)
    draw = ImageDraw.Draw(image)
    draw.text((1144, 58), "DIVE LOG", font=_font(17, bold=True), fill="#deeeeb", anchor="rt")

    title_font, lines, title_step, title_height = _layout_title(draw, dive["site_name"], width=730, height=160)
    title_top = round(244 - title_height / 2)
    for index, line in enumerate(lines):
        draw.text((54, title_top + index * title_step), line, font=title_font, fill="white", anchor="lt")
    location_font = _font(25)
    draw.text((56, title_top + title_height + 23),
              _fit_line(draw, dive["country_or_area"] or "Dive log", location_font, 730),
              font=location_font, fill="#b8cecf", anchor="lt")

    draw.line((56, 403, 1144, 403), fill="#426064", width=1)
    stats = _select_share_stats(dive, length_unit=length_unit, weight_unit=weight_unit)
    column_width = (1088 - 28 * max(0, len(stats) - 1)) / max(1, len(stats))
    size = _equal_stat_size(draw, stats, column_width, unit_size=26, max_size=68)
    for index, (value, unit, label) in enumerate(stats):
        _draw_stat(draw, 56 + index * (column_width + 28), 492, value, unit, label,
                   width=column_width, size=size, unit_size=26)

    footer_font = _font(20)
    footer = f"{dive['username']}  ·  {_display_date(dive['date'])}"
    draw.text((56, 592), _fit_line(draw, footer, footer_font, 690), font=footer_font, fill="#b8cecf", anchor="ls")
    stream = BytesIO()
    image.convert("RGB").save(stream, "JPEG", quality=92)
    stream.seek(0)
    return stream
