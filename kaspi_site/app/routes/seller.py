from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from ..auth import current_user, safe_next_url, seller_required
from ..constants import STATUS_CANCELLED
from ..db import get_db, next_id
from ..services import category_choices, parse_product_form

bp = Blueprint("seller", __name__, url_prefix="/seller")

LOW_STOCK = 5


def own_product(cur, product_id):
    cur.execute(
        """
        SELECT product_id, title, price, stock_qty, category_id, is_active
        FROM products WHERE product_id = %s AND seller_id = %s;
        """,
        (product_id, current_user()["seller_id"]),
    )
    row = cur.fetchone()
    if row is None:
        abort(404)
    return {
        "id": row[0], "title": row[1], "price": row[2],
        "stock_qty": row[3], "category_id": row[4], "is_active": row[5],
    }


@bp.route("/")
@seller_required
def dashboard():
    seller_id = current_user()["seller_id"]
    with get_db().cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FILTER (WHERE is_active),
                   COUNT(*) FILTER (WHERE NOT is_active)
            FROM products WHERE seller_id = %s;
            """,
            (seller_id,),
        )
        active, hidden = cur.fetchone()

        cur.execute(
            """
            SELECT COALESCE(SUM(oi.quantity * oi.unit_price), 0),
                   COALESCE(SUM(oi.quantity), 0),
                   COUNT(DISTINCT o.order_id)
            FROM order_items oi
            JOIN products p ON p.product_id = oi.product_id
            JOIN orders o ON o.order_id = oi.order_id
            WHERE p.seller_id = %s AND o.status <> %s;
            """,
            (seller_id, STATUS_CANCELLED),
        )
        revenue, units, orders_count = cur.fetchone()

        cur.execute(
            """
            SELECT product_id, title, stock_qty FROM products
            WHERE seller_id = %s AND is_active AND stock_qty <= %s
            ORDER BY stock_qty, product_id LIMIT 5;
            """,
            (seller_id, LOW_STOCK),
        )
        low_stock = cur.fetchall()

        cur.execute(
            """
            SELECT o.order_id, o.order_date, o.status, p.title, oi.quantity, oi.unit_price
            FROM order_items oi
            JOIN products p ON p.product_id = oi.product_id
            JOIN orders o ON o.order_id = oi.order_id
            WHERE p.seller_id = %s
            ORDER BY o.order_id DESC, oi.order_item_id LIMIT 6;
            """,
            (seller_id,),
        )
        recent = cur.fetchall()

    return render_template(
        "seller/dashboard.html",
        active=active, hidden=hidden, revenue=revenue, units=units,
        orders_count=orders_count, low_stock=low_stock, recent=recent,
    )


@bp.route("/products")
@seller_required
def products():
    q = request.args.get("q", "").strip()
    seller_id = current_user()["seller_id"]

    query = """
        SELECT p.product_id, p.title, p.price, p.stock_qty, p.is_active,
               COALESCE(par.name || ' › ', '') || c.name
        FROM products p
        JOIN categories c ON c.category_id = p.category_id
        LEFT JOIN categories par ON par.category_id = c.parent_category_id
        WHERE p.seller_id = %s
    """
    params = [seller_id]
    if q:
        query += " AND p.title ILIKE %s"
        params.append("%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")

    with get_db().cursor() as cur:
        cur.execute(query + " ORDER BY p.is_active DESC, p.product_id DESC;", params)
        rows = cur.fetchall()

    items = [
        {"id": r[0], "title": r[1], "price": r[2], "stock_qty": r[3], "is_active": r[4], "category": r[5]}
        for r in rows
    ]
    return render_template("seller/products.html", products=items, q=q, low_stock=LOW_STOCK)


def render_form(cur, product, errors=(), status=200):
    for message in errors:
        flash(message, "error")
    return render_template(
        "seller/product_form.html", product=product, categories=category_choices(cur)
    ), status


@bp.route("/products/new", methods=["GET", "POST"])
@seller_required
def product_new():
    conn = get_db()
    with conn.cursor() as cur:
        if request.method == "GET":
            return render_form(cur, {"title": "", "price": "", "stock_qty": 1, "category_id": None})

        categories = category_choices(cur)
        data, errors = parse_product_form(request.form, {c[0] for c in categories})
        if errors:
            return render_form(cur, request.form.to_dict() | {"category_id": request.form.get("category_id", type=int)}, errors, 400)

        cur.execute(
            """
            INSERT INTO products (product_id, seller_id, category_id, title, price, stock_qty)
            VALUES (%s, %s, %s, %s, %s, %s);
            """,
            (next_id(cur, "products", "product_id"), current_user()["seller_id"],
             data["category_id"], data["title"], data["price"], data["stock_qty"]),
        )
    conn.commit()
    flash(f"Товар «{data['title']}» добавлен и уже виден покупателям.", "success")
    return redirect(url_for("seller.products"))


@bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@seller_required
def product_edit(product_id):
    conn = get_db()
    with conn.cursor() as cur:
        product = own_product(cur, product_id)
        if request.method == "GET":
            return render_form(cur, product)

        categories = category_choices(cur)
        data, errors = parse_product_form(request.form, {c[0] for c in categories})
        if errors:
            form = request.form.to_dict() | {"category_id": request.form.get("category_id", type=int)}
            form["id"] = product_id
            return render_form(cur, form, errors, 400)

        cur.execute(
            """
            UPDATE products SET title = %s, price = %s, stock_qty = %s, category_id = %s
            WHERE product_id = %s AND seller_id = %s;
            """,
            (data["title"], data["price"], data["stock_qty"], data["category_id"],
             product_id, current_user()["seller_id"]),
        )
    conn.commit()
    flash("Изменения сохранены.", "success")
    return redirect(url_for("seller.products"))


@bp.route("/products/<int:product_id>/toggle", methods=["POST"])
@seller_required
def product_toggle(product_id):
    conn = get_db()
    with conn.cursor() as cur:
        product = own_product(cur, product_id)
        cur.execute(
            "UPDATE products SET is_active = NOT is_active WHERE product_id = %s;", (product_id,)
        )
    conn.commit()
    flash(
        f"«{product['title']}» {'скрыт из каталога' if product['is_active'] else 'снова в каталоге'}.",
        "success",
    )
    return redirect(safe_next_url(request.form.get("next")) or url_for("seller.products"))


@bp.route("/orders")
@seller_required
def orders():
    with get_db().cursor() as cur:
        cur.execute(
            """
            SELECT o.order_id, o.order_date, o.status, u.full_name, u.phone,
                   p.title, oi.quantity, oi.unit_price
            FROM order_items oi
            JOIN products p ON p.product_id = oi.product_id
            JOIN orders o ON o.order_id = oi.order_id
            JOIN users u ON u.user_id = o.user_id
            WHERE p.seller_id = %s
            ORDER BY o.order_id DESC, oi.order_item_id;
            """,
            (current_user()["seller_id"],),
        )
        rows = cur.fetchall()

    orders = {}
    for order_id, date, status, buyer, phone, title, quantity, price in rows:
        order = orders.setdefault(
            order_id,
            {"order_id": order_id, "date": date, "status": status, "buyer": buyer,
             "phone": phone, "lines": [], "total": 0},
        )
        order["lines"].append({"title": title, "quantity": quantity, "price": price})
        order["total"] += price * quantity

    return render_template("seller/orders.html", orders=list(orders.values()))
