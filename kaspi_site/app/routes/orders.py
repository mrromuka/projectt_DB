from flask import Blueprint, abort, flash, redirect, render_template, url_for

from ..auth import current_user_id, login_required
from ..constants import STATUS_CANCELLED, STATUS_NEW
from ..db import get_db, next_id
from ..recommendations import get_user_recommendations
from ..services import set_order_status
from .cart import get_cart_id

bp = Blueprint("orders", __name__)


@bp.route("/checkout", methods=["POST"])
@login_required
def checkout():
    user_id = current_user_id()
    conn = get_db()

    with conn.cursor() as cur:
        cart_id = get_cart_id(cur, user_id)
        if cart_id is None:
            return redirect(url_for("catalog.home"))

        
        cur.execute(
            """
            SELECT ci.product_id, ci.quantity, p.price, p.stock_qty, p.is_active, p.title
            FROM cart_items ci
            JOIN products p ON ci.product_id = p.product_id
            WHERE ci.cart_id = %s
            ORDER BY ci.cart_item_id
            FOR UPDATE OF p;
            """,
            (cart_id,),
        )
        items = cur.fetchall()
        if not items:
            return redirect(url_for("cart.show"))

        for _, quantity, _, stock, active, title in items:
            if not active or stock < quantity:
                conn.rollback()
                flash(f"«{title}» недоступен в нужном количестве. Измените корзину.", "error")
                return redirect(url_for("cart.show"))

        order_id = next_id(cur, "orders", "order_id")
        cur.execute(
            """
            INSERT INTO orders (order_id, user_id, order_date, status)
            VALUES (%s, %s, NOW(), %s);
            """,
            (order_id, user_id, STATUS_NEW),
        )

        first_item_id = next_id(cur, "order_items", "order_item_id")
        cur.executemany(
            """
            INSERT INTO order_items (order_item_id, order_id, product_id, quantity, unit_price)
            VALUES (%s, %s, %s, %s, %s);
            """,
            [
                (first_item_id + index, order_id, product_id, quantity, price)
                for index, (product_id, quantity, price, *_rest) in enumerate(items)
            ],
        )
        cur.executemany(
            "UPDATE products SET stock_qty = stock_qty - %s WHERE product_id = %s;",
            [(quantity, product_id) for product_id, quantity, *_rest in items],
        )

        cur.execute("DELETE FROM cart_items WHERE cart_id = %s;", (cart_id,))

    conn.commit()
    flash(f"Заказ №{order_id} оформлен. Мы сообщим, когда статус изменится.", "success")
    return redirect(url_for("orders.history"))


@bp.route("/orders")
@login_required
def history():
    with get_db().cursor() as cur:
        cur.execute(
            """
            SELECT o.order_id, o.order_date, o.status,
                   p.product_id, p.title, oi.quantity, oi.unit_price
            FROM orders o
            JOIN order_items oi ON o.order_id = oi.order_id
            JOIN products p ON oi.product_id = p.product_id
            WHERE o.user_id = %s
            ORDER BY o.order_id DESC, oi.order_item_id;
            """,
            (current_user_id(),),
        )
        rows = cur.fetchall()

        recommendations = get_user_recommendations(cur, current_user_id())

    orders = {}
    for order_id, date, status, product_id, title, quantity, price in rows:
        order = orders.setdefault(
            order_id,
            {"order_id": order_id, "date": date, "status": status, "lines": [], "total": 0},
        )
        order["lines"].append(
            {"product_id": product_id, "title": title, "quantity": quantity, "price": price}
        )
        order["total"] += price * quantity

    return render_template(
        "orders.html", orders=list(orders.values()), recommendations=recommendations
    )


@bp.route("/orders/<int:order_id>/cancel", methods=["POST"])
@login_required
def cancel(order_id):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM orders WHERE order_id = %s AND user_id = %s;",
            (order_id, current_user_id()),
        )
        row = cur.fetchone()
        if row is None:
            abort(404)
        if row[0] != STATUS_NEW:
            flash("Отменить можно только новый заказ.", "error")
            return redirect(url_for("orders.history"))

        _, message = set_order_status(cur, order_id, STATUS_CANCELLED)
    conn.commit()
    flash(f"Заказ №{order_id} отменён.", "success")
    return redirect(url_for("orders.history"))
