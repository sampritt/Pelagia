"""Passwordless email authentication with server-side, single-use challenges."""
import hashlib
import hmac
import re
import secrets
import time
from sqlite3 import IntegrityError

import requests
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for

from . import db as database
from .google_auth import check_csrf, finish_login

bp = Blueprint('email_auth', __name__, url_prefix='/auth/email')
TTL = 600


def available():
    return bool(current_app.config.get('RESEND_API_KEY') and current_app.config.get('EMAIL_FROM'))


def init_app(app):
    app.register_blueprint(bp)
    app.context_processor(lambda: {'email_login_available': available()})
    @app.after_request
    def private_auth(response):
        if request.path.startswith('/auth/') or request.path in ('/login', '/signup'):
            response.headers['Cache-Control'] = 'no-store'
        return response


def digest(value):
    return hmac.new(current_app.secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()


def send_code(email, code):
    response = requests.post('https://api.resend.com/emails', headers={
        'Authorization': 'Bearer ' + current_app.config['RESEND_API_KEY'],
    }, json={
        'from': current_app.config['EMAIL_FROM'], 'to': [email],
        'subject': 'Your Pelagia sign-in code',
        'text': f'Your Pelagia code is {code}.\n\nIt expires in 10 minutes and can only be used once. Enter it in the window where you requested it.\n\nIf you did not request this code, you can ignore this email.',
        'html': f'<div style="font-family:Arial,sans-serif;color:#14363d;max-width:480px;margin:auto;padding:32px"><h1>Pelagia</h1><h2>Your sign-in code</h2><p>Return to Pelagia and enter:</p><p style="font-size:36px;letter-spacing:8px;font-weight:bold">{code}</p><p>This code expires in 10 minutes and works once.</p><p>If you didn’t request this, you can ignore this email.</p></div>',
    }, timeout=10)
    response.raise_for_status()


@bp.route('/start', methods=['GET', 'POST'])
def start():
    from . import _safe_next_url
    if not available():
        abort(404)
    destination = _safe_next_url(request.values.get('next'))
    if session.get('user_id'):
        return redirect(destination)
    if request.method == 'GET':
        return render_template('email_start.html', auth_next=destination)
    check_csrf()
    email = request.form.get('email', '').strip().lower()
    if len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        flash('Enter a valid email address.')
        return render_template('email_start.html', auth_next=destination, email=email), 400
    db = database.get_db()
    now = time.time()
    address = digest(request.remote_addr or 'unknown')
    # Reserve sends atomically across workers; retain one day of abuse counters.
    db.execute('BEGIN IMMEDIATE')
    db.execute('DELETE FROM email_challenges WHERE created < ?', (now - 86400,))
    recent = db.execute('SELECT COUNT(*) FROM email_challenges WHERE (email = ? OR ip = ?) AND created > ?', (email, address, now - 3600)).fetchone()[0]
    last = db.execute('SELECT MAX(created) FROM email_challenges WHERE email = ?', (email,)).fetchone()[0]
    if recent >= 10 or (last and now - last < 60):
        db.rollback()
        flash('Please wait before requesting another code. You can use the latest code we sent.')
        return render_template('email_start.html', auth_next=destination, email=email), 429
    challenge = secrets.token_urlsafe(32)
    code = f'{secrets.randbelow(1000000):06d}'
    db.execute('INSERT INTO email_challenges (id, email, code_hash, created, ip) VALUES (?, ?, ?, ?, ?)',
               (challenge, email, digest(challenge + code), now, address))
    db.commit()
    try:
        send_code(email, code)
    except requests.RequestException:
        db.execute('UPDATE email_challenges SET consumed = 1 WHERE id = ?', (challenge,))
        db.commit()
        current_app.logger.warning('Email sign-in delivery failed')
        flash('We couldn’t send your code. Please try again shortly or continue with Google.')
        return render_template('email_start.html', auth_next=destination, email=email), 503
    session.pop('email_pending', None)
    session['email_challenge'] = {'id': challenge, 'next': destination}
    return redirect(url_for('email_auth.verify'))


@bp.route('/verify', methods=['GET', 'POST'])
def verify():
    if not available():
        abort(404)
    flow = session.get('email_challenge', {})
    db = database.get_db()
    if request.method == 'POST':
        check_csrf()
        db.execute('BEGIN IMMEDIATE')
    row = db.execute('SELECT * FROM email_challenges WHERE id = ?', (flow.get('id', ''),)).fetchone()
    if not row or row['consumed'] or row['attempts'] >= 5 or time.time() - row['created'] > TTL or row['link_user'] != session.get('user_id'):
        db.rollback()
        flash('Your code expired or was already used. Please request a new one.')
        return redirect(url_for('email_auth.start', next=flow.get('next')))
    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        db.execute('UPDATE email_challenges SET attempts = attempts + 1 WHERE id = ?', (row['id'],))
        if not hmac.compare_digest(row['code_hash'], digest(row['id'] + code)):
            db.commit()
            flash('That code didn’t match. Try again, or request a new code.')
        else:
            db.execute('UPDATE email_challenges SET consumed = 1 WHERE id = ?', (row['id'],))
            users = matching_users(db, row['email'])
            db.commit()
            if len(users) > 1:
                flash('This email matches more than one account. Please continue with Google or contact support.')
                return redirect(url_for('login'))
            if users:
                return finish_login(users[0]['id'], flow.get('next'))
            session.clear()
            session['email_pending'] = {'email': row['email'], 'created': time.time(), 'next': flow.get('next')}
            return redirect(url_for('email_auth.signup'))
    return render_template('email_verify.html', email=row['email'], auth_next=flow.get('next'))


def matching_users(db, email):
    # A correct code proves access to this address. Match either sign-in method,
    # deduplicating the same user; never choose between different accounts.
    return db.execute(
        'SELECT id FROM users WHERE lower(login_email) = ? OR lower(google_email) = ? LIMIT 2',
        (email, email),
    ).fetchall()


@bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if not available():
        abort(404)
    pending = session.get('email_pending')
    if not pending or time.time() - pending['created'] > TTL:
        flash('Please verify your email again to continue.')
        return redirect(url_for('email_auth.start'))
    username = ''
    if request.method == 'POST':
        check_csrf()
        username = request.form.get('username', '').strip()
        if not 3 <= len(username) <= 40:
            flash('Choose a username between 3 and 40 characters.')
        else:
            db = database.get_db()
            db.execute('BEGIN IMMEDIATE')
            users = matching_users(db, pending['email'])
            if users:
                db.rollback()
                if len(users) == 1:
                    return finish_login(users[0]['id'], pending.get('next'))
                session.pop('email_pending', None)
                flash('This email matches more than one account. Please continue with Google or contact support.')
                return redirect(url_for('login'))
            try:
                cur = db.execute('INSERT INTO users (username, login_email) VALUES (?, ?)', (username, pending['email']))
                db.commit()
            except IntegrityError:
                db.rollback()
                user = db.execute('SELECT id FROM users WHERE login_email = ?', (pending['email'],)).fetchone()
                if user:
                    return finish_login(user['id'], pending.get('next'))
                flash('That username is already taken. Please choose another.')
            else:
                return finish_login(cur.lastrowid, pending.get('next'))
    return render_template('email_signup.html', username=username)
