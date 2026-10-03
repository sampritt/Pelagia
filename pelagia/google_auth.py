"""Optional Google sign-in, using validated OpenID Connect identities."""

import secrets
import time
from sqlite3 import IntegrityError

from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.flask_client import OAuth
from authlib.oidc.core import UserInfo
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from joserfc.errors import JoseError
from requests.exceptions import RequestException

from . import db as database


bp = Blueprint("google_auth", __name__, url_prefix="/auth/google")
FLOW_TTL_SECONDS = 600


def is_available():
    return bool(current_app.config.get("GOOGLE_CLIENT_ID") and current_app.config.get("GOOGLE_CLIENT_SECRET"))


def init_app(app):
    oauth = OAuth(app)
    oauth.register(
        "google",
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email", "code_challenge_method": "S256", "default_timeout": 10},
    )
    app.register_blueprint(bp)
    app.context_processor(template_context)


def template_context():
    linked = False
    if is_available() and session.get("user_id"):
        user = database.get_db().execute(
            "SELECT google_subject FROM users WHERE id = ?", (session["user_id"],)
        ).fetchone()
        linked = bool(user and user["google_subject"])
    return {"google_login_available": is_available(), "google_is_linked": linked, "google_csrf_token": csrf_token}


def csrf_token():
    if "google_csrf" not in session:
        session["google_csrf"] = secrets.token_urlsafe(32)
    return session["google_csrf"]


def check_csrf():
    expected = session.get("google_csrf", "")
    supplied = request.form.get("csrf_token", "")
    if not expected or not secrets.compare_digest(expected, supplied):
        abort(400)


def clear_flow():
    session.pop("google_flow", None)
    # Authlib keeps state, nonce and PKCE verifier here until the callback.
    for key in list(session):
        if key.startswith("_state_google_"):
            session.pop(key, None)


def begin_flow(mode):
    if not is_available():
        abort(404)
    clear_flow()
    session.pop("google_pending", None)
    state = secrets.token_urlsafe(32)
    session["google_flow"] = {
        "state": state, "mode": mode, "user_id": session.get("user_id"), "started_at": time.time()
    }
    redirect_uri = current_app.config.get("GOOGLE_REDIRECT_URI") or url_for("google_auth.callback", _external=True)
    try:
        return current_app.extensions["authlib.integrations.flask_client"].google.authorize_redirect(
            redirect_uri, state=state, prompt="select_account"
        )
    except (OAuthError, JoseError, RequestException):
        clear_flow()
        flash("Google sign-in is temporarily unavailable. Please try again.")
        return redirect(url_for("profile" if mode == "link" else "landing"))


@bp.get("/login")
def login():
    if session.get("user_id"):
        return redirect(url_for("home"))
    return begin_flow("login")


@bp.post("/link")
def link():
    if not is_available():
        abort(404)
    user = database.get_db().execute("SELECT id FROM users WHERE id = ?", (session.get("user_id"),)).fetchone()
    if not user:
        return redirect(url_for("landing"))
    check_csrf()
    return begin_flow("link")


@bp.get("/callback")
def callback():
    if not is_available():
        abort(404)
    flow = session.get("google_flow")
    state = request.args.get("state", "")
    if (
        not flow
        or not secrets.compare_digest(flow["state"], state)
        or time.time() - flow["started_at"] > FLOW_TTL_SECONDS
        or flow["user_id"] != session.get("user_id")
    ):
        clear_flow()
        flash("Your Google sign-in expired. Please start again.")
        return redirect(url_for("landing"))
    destination = "profile" if flow["mode"] == "link" else "landing"
    try:
        # Authlib checks state and validates the ID token's signature, issuer,
        # audience, expiry and nonce. Do not substitute unverified token data.
        token = current_app.extensions["authlib.integrations.flask_client"].google.authorize_access_token()
        identity = token.get("userinfo")
        if (
            not token.get("id_token")
            or not isinstance(identity, UserInfo)
            or not isinstance(identity.get("sub"), str)
            or not identity["sub"]
            or not isinstance(identity.get("email"), str)
            or not identity["email"]
            or identity.get("email_verified") is not True
        ):
            flash("Google could not confirm your account's email address. Please use another account.")
            return redirect(url_for(destination))
    except (OAuthError, JoseError, RequestException):
        flash("Google sign-in could not be completed. Please try again.")
        return redirect(url_for(destination))
    finally:
        clear_flow()

    db = database.get_db()
    user = db.execute("SELECT id FROM users WHERE google_subject = ?", (identity["sub"],)).fetchone()
    if flow["mode"] == "link":
        return link_identity(identity, flow["user_id"], user)
    if user:
        db.execute("UPDATE users SET google_email = ? WHERE id = ?", (identity["email"], user["id"]))
        db.commit()
        return finish_login(user["id"])

    session.clear()
    session["google_pending"] = {"sub": identity["sub"], "email": identity["email"], "started_at": time.time()}
    return redirect(url_for("google_auth.signup"))


def link_identity(identity, user_id, existing_identity):
    db = database.get_db()
    user = db.execute("SELECT google_subject FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        session.clear()
        return redirect(url_for("landing"))
    if existing_identity and existing_identity["id"] != user_id:
        flash("That Google account is already linked to another Pelagia account.")
    elif user["google_subject"] and user["google_subject"] != identity["sub"]:
        flash("Your Pelagia account already has a different Google account linked.")
    else:
        try:
            # The conditional update also protects against concurrent linking.
            updated = db.execute(
                "UPDATE users SET google_subject = ?, google_email = ? "
                "WHERE id = ? AND (google_subject IS NULL OR google_subject = ?)",
                (identity["sub"], identity["email"], user_id, identity["sub"]),
            )
            db.commit()
        except IntegrityError:
            db.rollback()
            flash("That Google account is already linked to another Pelagia account.")
        else:
            flash("Google sign-in is now linked to your account." if updated.rowcount else "Your account already has another Google account linked.")
    return redirect(url_for("profile"))


def finish_login(user_id):
    session.clear()
    session["user_id"] = user_id
    return redirect(url_for("home"))


@bp.route("/signup", methods=("GET", "POST"))
def signup():
    if not is_available():
        abort(404)
    pending = session.get("google_pending")
    if not pending or time.time() - pending["started_at"] > FLOW_TTL_SECONDS:
        session.pop("google_pending", None)
        flash("Your Google sign-in expired. Please start again.")
        return redirect(url_for("landing"))
    username = ""
    if request.method == "POST":
        check_csrf()
        username = request.form.get("username", "").strip()
        if not 3 <= len(username) <= 40:
            flash("Choose a username between 3 and 40 characters.")
        else:
            db = database.get_db()
            try:
                # An empty hash explicitly disables password login and avoids
                # rebuilding the legacy users table and its foreign keys.
                cur = db.execute(
                    "INSERT INTO users (username, password_hash, google_subject, google_email) VALUES (?, '', ?, ?)",
                    (username, pending["sub"], pending["email"]),
                )
                db.commit()
            except IntegrityError:
                db.rollback()
                user = db.execute("SELECT id FROM users WHERE google_subject = ?", (pending["sub"],)).fetchone()
                if user:
                    return finish_login(user["id"])
                flash("That username is already taken. Please choose another.")
            else:
                return finish_login(cur.lastrowid)
    return render_template("google_signup.html", username=username)
