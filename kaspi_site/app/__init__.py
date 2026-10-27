from decimal import Decimal

from flask import Flask, render_template, session

from . import auth, cli, db
from .config import Config
from .recommendations import get_recommendations
from .constants import ORDER_STATUSES, ROLE_LABELS, STATUS_LABELS
from .routes import register_blueprints


def money(value):
    """12500 -> '12 500', 12500.5 -> '12 500,50'."""
    if value is None:
        return "0"
    value = Decimal(value)
    if value == value.to_integral_value():
        return f"{int(value):,}".replace(",", " ")
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    auth.init_app(app)
    cli.init_app(app)
    register_blueprints(app)

    app.jinja_env.filters["money"] = money
    app.jinja_env.filters["status_label"] = lambda s: STATUS_LABELS.get(s, s)
    app.jinja_env.filters["role_label"] = lambda r: ROLE_LABELS.get(r, r)
    app.jinja_env.filters["dict_merge"] = lambda a, b: {**a, **b}
    app.jinja_env.globals["ORDER_STATUSES"] = ORDER_STATUSES

    @app.context_processor
    def inject_globals():
        user = auth.current_user()
        cart_count = 0
        if user:
            with db.get_db().cursor() as cur:
                cur.execute(
                    """
                    SELECT COALESCE(SUM(ci.quantity), 0)
                    FROM carts c JOIN cart_items ci ON ci.cart_id = c.cart_id
                    WHERE c.user_id = %s;
                    """,
                    (user["id"],),
                )
                cart_count = cur.fetchone()[0]
        # Только что добавили товар в корзину? Покажем (один раз) что к нему подходит.
        just_added = session.pop("just_added", None) if user else None
        added_recs = []
        if just_added:
            with db.get_db().cursor() as cur:
                added_recs = get_recommendations(cur, [just_added["id"]])
        return {
            "user": user,
            "cart_count": cart_count,
            "just_added": just_added,
            "added_recs": added_recs,
        }

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    def show_error(error):
        messages = {
            400: ("Некорректный запрос", getattr(error, "description", "")),
            403: ("Нет доступа", "У вас нет прав для просмотра этой страницы."),
            404: ("Страница не найдена", "Возможно, она была удалена или адрес введён неверно."),
        }
        title, text = messages[error.code]
        return render_template("error.html", code=error.code, title=title, text=text), error.code

    return app
