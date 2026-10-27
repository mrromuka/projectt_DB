import re

from flask import Blueprint, flash, redirect, render_template, request, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from ..auth import current_user, log_in, log_out, login_required, safe_next_url
from ..constants import ROLE_BUYER, ROLE_SELLER
from ..db import get_db, next_id

bp = Blueprint("account", __name__)

MIN_PASSWORD_LENGTH = 6
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def home_for(user):
    if user["is_admin"]:
        return url_for("admin.dashboard")
    if user["is_seller"]:
        return url_for("seller.dashboard")
    return url_for("catalog.home")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(home_for(current_user()))

    if request.method == "GET":
        return render_template("register.html", form={"role": request.args.get("role", ROLE_BUYER)})

    form = {
        "full_name": request.form.get("full_name", "").strip(),
        "email": request.form.get("email", "").strip().lower(),
        "phone": request.form.get("phone", "").strip(),
        "role": request.form.get("role", ROLE_BUYER),
        "company_name": request.form.get("company_name", "").strip(),
    }
    password = request.form.get("password", "")
    password2 = request.form.get("password2", "")

    errors = []
    if form["role"] not in (ROLE_BUYER, ROLE_SELLER):
        form["role"] = ROLE_BUYER
    if not form["full_name"]:
        errors.append("Укажите ФИО.")
    if not EMAIL_RE.match(form["email"]):
        errors.append("Укажите корректный email.")
    if len(password) < MIN_PASSWORD_LENGTH:
        errors.append(f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов.")
    if password != password2:
        errors.append("Пароли не совпадают.")
    if form["role"] == ROLE_SELLER and not form["company_name"]:
        errors.append("Укажите название магазина или компании.")

    conn = get_db()
    with conn.cursor() as cur:
        if not errors:
            cur.execute("SELECT 1 FROM users WHERE lower(email) = %s;", (form["email"],))
            if cur.fetchone():
                errors.append("Пользователь с таким email уже зарегистрирован. Попробуйте войти.")

        if errors:
            for message in errors:
                flash(message, "error")
            return render_template("register.html", form=form), 400

        user_id = next_id(cur, "users", "user_id")
        cur.execute(
            """
            INSERT INTO users (user_id, full_name, email, phone, password_hash, role)
            VALUES (%s, %s, %s, %s, %s, %s);
            """,
            (user_id, form["full_name"], form["email"], form["phone"],
             generate_password_hash(password), form["role"]),
        )
        if form["role"] == ROLE_SELLER:
            cur.execute(
                """
                INSERT INTO sellers (seller_id, company_name, contact_email, user_id)
                VALUES (%s, %s, %s, %s);
                """,
                (next_id(cur, "sellers", "seller_id"), form["company_name"], form["email"], user_id),
            )
    conn.commit()

    log_in(user_id)
    flash("Добро пожаловать! Аккаунт создан.", "success")
    return redirect(home_for(current_user()))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(home_for(current_user()))

    next_url = safe_next_url(request.values.get("next"))
    if request.method == "GET":
        return render_template("login.html", next_url=next_url, email="")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    with get_db().cursor() as cur:
        cur.execute(
            "SELECT user_id, password_hash, is_active FROM users WHERE lower(email) = %s;",
            (email,),
        )
        row = cur.fetchone()

    error = None
    if row is None or not row[1] or not check_password_hash(row[1], password):
        error = "Неверный email или пароль."
        if row is not None and not row[1]:
            error = "Для этого аккаунта пароль не задан. Обратитесь к администратору."
    elif not row[2]:
        error = "Аккаунт заблокирован."

    if error:
        flash(error, "error")
        return render_template("login.html", next_url=next_url, email=email), 401

    log_in(row[0])
    return redirect(next_url or home_for(current_user()))


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    log_out()
    flash("Вы вышли из аккаунта.", "info")
    return redirect(url_for("catalog.home"))
