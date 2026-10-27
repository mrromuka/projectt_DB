from pathlib import Path

import click
from werkzeug.security import generate_password_hash

from .constants import ROLE_ADMIN
from .db import get_db, next_id

MIGRATIONS = Path(__file__).resolve().parent.parent / "db" / "migration_001_roles.sql"


def init_app(app):
    @app.cli.command("init-db")
    def init_db():
        """Применить миграцию: роли, пароли, привязка продавцов."""
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(MIGRATIONS.read_text(encoding="utf-8"))
        conn.commit()
        click.echo("Миграция применена.")

    @app.cli.command("create-admin")
    @click.option("--email", prompt="Email администратора")
    @click.option("--name", prompt="Имя", default="Администратор")
    @click.password_option("--password", prompt="Пароль")
    def create_admin(email, name, password):
        """Создать администратора (или сделать админом существующего пользователя)."""
        email = email.strip().lower()
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users WHERE lower(email) = %s;", (email,))
            row = cur.fetchone()
            if row:
                cur.execute(
                    "UPDATE users SET role = %s, is_active = TRUE, password_hash = %s WHERE user_id = %s;",
                    (ROLE_ADMIN, generate_password_hash(password), row[0]),
                )
                click.echo(f"Пользователь {email} теперь администратор.")
            else:
                cur.execute(
                    """
                    INSERT INTO users (user_id, full_name, email, phone, password_hash, role)
                    VALUES (%s, %s, %s, '', %s, %s);
                    """,
                    (next_id(cur, "users", "user_id"), name, email, generate_password_hash(password), ROLE_ADMIN),
                )
                click.echo(f"Администратор {email} создан.")
        conn.commit()

    @app.cli.command("set-password")
    @click.argument("email")
    @click.password_option("--password", prompt="Новый пароль")
    def set_password(email, password):
        """Задать пароль существующему пользователю (для старых аккаунтов без пароля)."""
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET password_hash = %s WHERE lower(email) = %s;",
                (generate_password_hash(password), email.strip().lower()),
            )
            updated = cur.rowcount
        conn.commit()
        click.echo("Пароль обновлён." if updated else "Пользователь не найден.")
