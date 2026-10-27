import secrets
from functools import wraps
from urllib.parse import urlparse

from flask import abort, flash, g, redirect, request, session, url_for
from markupsafe import Markup

from .constants import ROLE_ADMIN, ROLE_SELLER
from .db import get_db




def current_user():
    """Пользователь из сессии (dict) или None. Читается из БД один раз за запрос,
    поэтому блокировка или смена роли действуют сразу."""
    if "current_user" in g:
        return g.current_user

    g.current_user = None
    user_id = session.get("user_id")
    if user_id is None:
        return None

    with get_db().cursor() as cur:
        cur.execute(
            """
            SELECT u.user_id, u.full_name, u.email, u.role, u.is_active,
                   s.seller_id, s.company_name
            FROM users u
            LEFT JOIN sellers s ON s.user_id = u.user_id
            WHERE u.user_id = %s;
            """,
            (user_id,),
        )
        row = cur.fetchone()

    if row is None or not row[4]:
        session.clear()
        return None

    g.current_user = {
        "id": row[0],
        "full_name": row[1],
        "email": row[2],
        "role": row[3],
        "seller_id": row[5],
        "company_name": row[6],
        "is_admin": row[3] == ROLE_ADMIN,
        "is_seller": row[3] == ROLE_SELLER and row[5] is not None,
    }
    return g.current_user


def current_user_id():
    user = current_user()
    return user["id"] if user else None


def log_in(user_id):
    session.clear()
    session["user_id"] = user_id
    g.pop("current_user", None)  

def log_out():
    session.clear()
    g.pop("current_user", None)


def safe_next_url(target):
    """Разрешаем редирект только на внутренние адреса сайта."""
    if not target:
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/") or target.startswith("//"):
        return None
    return target




def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            flash("Войдите в аккаунт, чтобы продолжить.", "info")
            next_url = request.full_path.rstrip("?") if request.method == "GET" else None
            return redirect(url_for("account.login", next=next_url))
        return view(*args, **kwargs)

    return wrapped


def role_required(check):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not check(current_user()):
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


admin_required = role_required(lambda u: u["is_admin"])
seller_required = role_required(lambda u: u["is_seller"])




def csrf_token():
    token = session.get("_csrf")
    if token is None:
        token = session["_csrf"] = secrets.token_urlsafe(32)
    return token


def csrf_field():
    return Markup('<input type="hidden" name="_csrf" value="%s">') % csrf_token()


def init_app(app):
    app.jinja_env.globals["csrf_field"] = csrf_field

    @app.before_request
    def verify_csrf():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            sent = request.form.get("_csrf", "")
            expected = session.get("_csrf", "")
            if not expected or not secrets.compare_digest(sent, expected):
                abort(400, "Форма устарела. Обновите страницу и попробуйте снова.")
