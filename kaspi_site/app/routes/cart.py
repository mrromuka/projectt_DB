from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from ..auth import current_user_id, login_required
from ..db import get_db, next_id
from ..recommendations import get_user_recommendations

bp = Blueprint("cart", __name__)


def get_cart_id(cur, user_id):
    cur.execute("SELECT cart_id FROM carts WHERE user_id = %s;", (user_id,))
    row = cur.fetchone()
    return row[0] if row else None


def create_cart(cur, user_id):
    cart_id = next_id(cur, "carts", "cart_id")
    cur.execute(
        "INSERT INTO carts (cart_id, user_id) VALUES (%s, %s);",
        (cart_id, user_id),
    )
    return cart_id


@bp.route("/add_to_cart/<int:product_id>", methods=["POST"])
@login_required
def add_item(product_id):
    user_id = current_user_id()
    conn = get_db()

    with conn.cursor() as cur:
        cur.execute(
            "SELECT title, stock_qty FROM products WHERE product_id = %s AND is_active;",
            (product_id,),
        )
        product = cur.fetchone()
        if product is None:
            abort(404)

        cart_id = get_cart_id(cur, user_id)
        if cart_id is None:
            cart_id = create_cart(cur, user_id)

        cur.execute(
            "SELECT cart_item_id, quantity FROM cart_items WHERE cart_id = %s AND product_id = %s;",
            (cart_id, product_id),
        )
        item = cur.fetchone()
        in_cart = item[1] if item else 0

        if in_cart + 1 > product[1]:
            flash(f"«{product[0]}»: в наличии только {product[1]} шт.", "error")
            conn.commit()
            return redirect(request.referrer or url_for("cart.show"))

        if item:
            cur.execute(
                "UPDATE cart_items SET quantity = quantity + 1 WHERE cart_item_id = %s;",
                (item[0],),
            )
        else:
            cur.execute(
                """
                INSERT INTO cart_items (cart_item_id, cart_id, product_id, quantity)
                VALUES (%s, %s, %s, 1);
                """,
                (next_id(cur, "cart_items", "cart_item_id"), cart_id, product_id),
            )

    conn.commit()
    flash(f"«{product[0]}» добавлен в корзину.", "success")
    # base.html покажет один раз панель «Вам может понравиться» для этого товара
    session["just_added"] = {"id": product_id, "title": product[0]}
    return redirect(request.referrer or url_for("cart.show"))


@bp.route("/cart/update/<int:product_id>", methods=["POST"])
@login_required
def update_item(product_id):
    action = request.form.get("action")
    conn = get_db()

    with conn.cursor() as cur:
        cart_id = get_cart_id(cur, current_user_id())
        if cart_id is None:
            return redirect(url_for("cart.show"))

        cur.execute(
            """
            SELECT ci.cart_item_id, ci.quantity, p.stock_qty, p.title
            FROM cart_items ci JOIN products p ON p.product_id = ci.product_id
            WHERE ci.cart_id = %s AND ci.product_id = %s;
            """,
            (cart_id, product_id),
        )
        item = cur.fetchone()
        if item is None:
            return redirect(url_for("cart.show"))
        item_id, quantity, stock, title = item

        if action == "remove" or (action == "dec" and quantity <= 1):
            cur.execute("DELETE FROM cart_items WHERE cart_item_id = %s;", (item_id,))
        elif action == "dec":
            cur.execute("UPDATE cart_items SET quantity = quantity - 1 WHERE cart_item_id = %s;", (item_id,))
        elif action == "inc":
            if quantity + 1 > stock:
                flash(f"«{title}»: в наличии только {stock} шт.", "error")
            else:
                cur.execute("UPDATE cart_items SET quantity = quantity + 1 WHERE cart_item_id = %s;", (item_id,))
        else:
            abort(400)

    conn.commit()
    return redirect(url_for("cart.show"))


@bp.route("/cart")
@login_required
def show():
    cart_items = []

    with get_db().cursor() as cur:
        cart_id = get_cart_id(cur, current_user_id())

        if cart_id is not None:
            cur.execute(
                """
                SELECT p.product_id, p.title, p.price, ci.quantity, p.price * ci.quantity,
                       p.stock_qty, p.is_active, s.company_name
                FROM cart_items ci
                JOIN products p ON ci.product_id = p.product_id
                JOIN sellers s ON s.seller_id = p.seller_id
                WHERE ci.cart_id = %s
                ORDER BY ci.cart_item_id;
                """,
                (cart_id,),
            )
            cart_items = [
                {
                    "product_id": product_id,
                    "title": title,
                    "price": price,
                    "quantity": quantity,
                    "subtotal": subtotal,
                    "stock": stock,
                    "available": active and stock >= quantity,
                    "seller": seller,
                }
                for product_id, title, price, quantity, subtotal, stock, active, seller in cur.fetchall()
            ]

    # Рекомендации показываем всегда: и с товарами в корзине, и в пустой (после покупки)
    with get_db().cursor() as cur:
        recommendations = get_user_recommendations(
            cur, current_user_id(), [i["product_id"] for i in cart_items]
        )

    session.pop("just_added", None)  # в корзине отдельная панель не нужна

    total_price = sum(item["subtotal"] for item in cart_items)
    can_checkout = bool(cart_items) and all(item["available"] for item in cart_items)

    return render_template(
        "cart.html",
        cart_items=cart_items,
        total_price=total_price,
        can_checkout=can_checkout,
        recommendations=recommendations,
    )
