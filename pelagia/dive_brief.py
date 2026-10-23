"""Disk-backed daily editions. Markdown is content, never executable HTML."""

import hashlib
import math
import os
import re
import secrets
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import click
import mistune
from flask import current_app, jsonify, request, url_for
from flask.cli import with_appcontext
from markupsafe import Markup
from werkzeug.exceptions import RequestEntityTooLarge


MAX_BRIEF_BYTES = 256 * 1024


@dataclass(frozen=True)
class DiveBrief:
    title: str
    effective_date: date
    headline: str
    body_html: Markup
    read_minutes: int

    @property
    def date_label(self):
        return self.effective_date.strftime("%A, %B %-d, %Y")


class BriefRenderer(mistune.HTMLRenderer):
    def link(self, text, url, title=None):
        link = super().link(text, url, title)
        if urlsplit(url).scheme.lower() in ("https", "http"):
            attributes = ' target="_blank" rel="noopener noreferrer"'
            if text.lower() == "read more":
                attributes += ' class="brief-source-link"'
            link = link.replace("<a ", f"<a{attributes} ", 1)
        return link


def _plain_text(tokens):
    return "".join(
        _plain_text(token["children"]) if "children" in token else token.get("raw", "")
        for token in tokens
    ).strip()


@lru_cache(maxsize=32)
def _read_edition(path_string, modified_ns, size):
    # The stat values invalidate the cache when an edition is replaced on disk.
    path = Path(path_string)
    edition = date.fromisoformat(path.stem.removeprefix("the_dive_brief_"))
    if size > MAX_BRIEF_BYTES:
        raise ValueError("Edition exceeds the 256 KiB size limit")
    return parse_edition(path.read_text(encoding="utf-8"), edition)


def parse_edition(markdown, edition):
    if "\x00" in markdown:
        raise ValueError("Markdown cannot contain null bytes")
    parser = mistune.create_markdown(renderer="ast", plugins=["table", "strikethrough"])
    tokens, state = parser.parse(markdown)
    blocks = [token for token in tokens if token["type"] != "blank_line"]
    if len(blocks) < 4 or blocks[0]["type"] != "heading" or blocks[0]["attrs"]["level"] != 1:
        raise ValueError("Expected a title, date, summary headline and story body")
    title = _plain_text(blocks.pop(0)["children"])
    date_block = blocks.pop(0)
    if date_block["type"] != "paragraph":
        raise ValueError("Expected an edition date after the title")
    written_date = datetime.strptime(_plain_text(date_block["children"]), "%A, %B %d, %Y").date()
    if written_date != edition:
        raise ValueError("Markdown date must match the edition filename")
    summary = blocks.pop(0)
    if summary["type"] != "paragraph":
        raise ValueError("Expected a summary headline after the date")
    headline = _plain_text(summary["children"])
    if not title or not headline:
        raise ValueError("Edition title and summary headline cannot be empty")
    if blocks and blocks[0]["type"] == "thematic_break":
        blocks.pop(0)
    if not blocks:
        raise ValueError("Edition story body cannot be empty")

    renderer = BriefRenderer(escape=True)
    # Register plugin renderers (tables) on the same safe HTML renderer.
    mistune.create_markdown(renderer=renderer, plugins=["table", "strikethrough"])
    sections, section = [], []
    for token in blocks:
        if token["type"] == "heading" and token["attrs"]["level"] == 2 and section:
            sections.append(section)
            section = []
        if token["type"] != "thematic_break":
            section.append(token)
    if section:
        sections.append(section)
    if not sections:
        raise ValueError("Edition story body cannot be empty")
    html = "".join(f'<section class="brief-story">{renderer(part, state)}</section>' for part in sections)
    words = len(re.findall(r"\S+", _plain_text(blocks) + " " + headline))
    return DiveBrief(title, edition, headline, Markup(html), max(1, math.ceil(words / 220)))


def effective_date():
    """Publication day in the editorial timezone; the news may cover T-1."""
    return datetime.now(ZoneInfo(current_app.config["DIVE_BRIEF_TIMEZONE"])).date()


def load_brief(edition=None):
    target = edition or effective_date()
    if target > effective_date():
        return None
    path = Path(current_app.config["DIVE_BRIEF_DIR"]) / edition_filename(target)
    try:
        if not path.is_file():
            return None
        stat = path.stat()
        return _read_edition(str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    except (OSError, UnicodeError, ValueError) as error:
        current_app.logger.warning("Cannot load Dive Brief %s: %s", path.name, error)
    return None


def edition_filename(edition):
    return f"the_dive_brief_{edition.isoformat()}.md"


def _atomic_write(path, payload):
    """Readers see the complete previous or new edition, never a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def create_api_key(path, *, rotate=False):
    """Return the secret once; persist only its SHA-256 digest with mode 0600."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = "pdb_" + secrets.token_urlsafe(32)
    digest = (hashlib.sha256(key.encode()).hexdigest() + "\n").encode()
    if rotate:
        _atomic_write(path, digest)
    else:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(digest)
            stream.flush()
            os.fsync(stream.fileno())
    return key


def _expected_key_digest():
    digest = current_app.config.get("DIVE_BRIEF_API_KEY_SHA256", "")
    if not digest:
        try:
            with Path(current_app.config["DIVE_BRIEF_API_KEY_FILE"]).open(encoding="ascii") as stream:
                digest = stream.read(129).strip()
        except (OSError, UnicodeError):
            return None
    return digest.lower() if re.fullmatch(r"[a-fA-F0-9]{64}", digest) else None


def init_app(app):
    @app.after_request
    def brief_upload_headers(response):
        if request.path == "/api/dive-brief":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/dive-brief")
    def upload_dive_brief():
        expected = _expected_key_digest()
        if expected is None:
            return jsonify(error="upload_unavailable", message="Dive Brief upload authentication is not configured."), 503
        # Authenticate before reading any bytes; sessions and URL keys cannot authorize uploads.
        authorization = request.headers.get("Authorization", "").split()
        token = authorization[1] if len(authorization) == 2 and authorization[0].lower() == "bearer" else ""
        supplied = hashlib.sha256(token.encode("utf-8")).hexdigest()
        if not token or len(token) > 512 or not secrets.compare_digest(expected, supplied):
            response = jsonify(error="unauthorized", message="A valid Bearer API key is required.")
            response.headers["WWW-Authenticate"] = 'Bearer realm="Dive Brief upload"'
            return response, 401
        if request.mimetype not in ("text/markdown", "text/plain"):
            return jsonify(error="unsupported_media_type", message="Send the Markdown file as a raw UTF-8 text/markdown body."), 415
        if request.mimetype_params.get("charset", "utf-8").lower() not in ("utf-8", "utf8"):
            return jsonify(error="invalid_encoding", message="Markdown must use UTF-8 encoding."), 415
        try:
            if request.content_length is not None and request.content_length > MAX_BRIEF_BYTES:
                raise RequestEntityTooLarge()
            payload = request.stream.read(MAX_BRIEF_BYTES + 1)
            if len(payload) > MAX_BRIEF_BYTES:
                raise RequestEntityTooLarge()
        except RequestEntityTooLarge:
            return jsonify(error="payload_too_large", message="Markdown must be no larger than 256 KiB."), 413
        edition = effective_date()
        try:
            markdown = payload.decode("utf-8-sig")
            parse_edition(markdown, edition)
        except (UnicodeError, ValueError) as error:
            return jsonify(error="invalid_markdown", message=str(error), expected_date=edition.isoformat()), 422
        path = Path(current_app.config["DIVE_BRIEF_DIR"]) / edition_filename(edition)
        try:
            _atomic_write(path, markdown.encode("utf-8"))
        except OSError:
            current_app.logger.exception("Cannot persist Dive Brief edition")
            return jsonify(error="storage_unavailable", message="The edition could not be saved. Please retry."), 503
        response = jsonify(date=edition.isoformat(), filename=path.name,
                           url=url_for("read_dive_brief", edition=edition.isoformat()))
        response.status_code = 201
        response.headers["Location"] = url_for("read_dive_brief", edition=edition.isoformat())
        return response

    app.cli.add_command(create_key_command)


@click.command("create-dive-brief-key")
@click.option("--rotate", is_flag=True, help="Replace the existing key and immediately revoke it.")
@with_appcontext
def create_key_command(rotate):
    """Generate a Dive Brief upload key. Copy the secret from this output once."""
    if current_app.config.get("DIVE_BRIEF_API_KEY_SHA256"):
        raise click.ClickException("An environment digest is configured; update that secret instead of the local key file.")
    try:
        key = create_api_key(current_app.config["DIVE_BRIEF_API_KEY_FILE"], rotate=rotate)
    except FileExistsError:
        raise click.ClickException("An API key already exists. Use --rotate to replace it.") from None
    except OSError:
        raise click.ClickException("The API key file could not be written.") from None
    click.echo(key)
