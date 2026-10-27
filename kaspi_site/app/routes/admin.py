from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from ..auth import admin_required, current_user, safe_next_url
from ..constants import ROLE_SELLER, ROLES, STATUS_CANCELLED
from ..db import get_db, next_id
from ..services import paginate, set_order_status

bp = Blueprint("admin", __name__, url_prefix="/admin")


def like(value):
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def back(default_endpoint):
    return redirect(safe_next_url(request.form.get("next")) or url_for(default_endpoint))


@bp.route("/")
@admin_required
def dashboard():
    with get_db().cursor() as cur:
        cur.execute(
            """
            SELECT (SELECT COUNT(*) FROM users WHERE role = 'buyer'),
                   (SELECT COUNT(*) FROM sellers),
                   (SELECT COUNT(*) FROM products WHERE is_active),
                   (SELECT COUNT(*) FROM orders),
                   (SELECT COALESCE(SUM(oi.quantity * oi.unit_price), 0)
                      FROM order_items oi JOIN orders o ON o.order_id = oi.order_id
                      WHERE o.status <> %s);
            """,
            (STATUS_CANCELLED,),
        )
        buyers, sellers, products, orders_total, revenue = cur.fetchone()

        cur.execute("SELECT status, COUNT(*) FROM orders GROUP BY status;")
        by_status = dict(cur.fetchall())

        cur.execute(
            """
            SELECT o.order_id, o.order_date, o.status, u.full_name,
                   COALESCE(SUM(oi.quantity * oi.unit_price), 0)
            FROM orders o
            JOIN users u ON u.user_id = o.user_id
            LEFT JOIN order_items oi ON oi.order_id = o.order_id
            GROUP BY o.order_id, u.user_id
            ORDER BY o.order_id DESC LIMIT 6;
            """
        )
        recent = cur.fetchall()

    return render_template(
        "admin/dashboard.html", buyers=buyers, sellers=sellers, products=products,
        orders_total=orders_total, revenue=revenue, by_status=by_status, recent=recent,
    )




@bp.route("/orders")
@admin_required
def orders():
    status = request.args.get("status", "")
    q = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)

    where, params = ["TRUE"], []
    if status:
        where.append("o.status = %s")
        params.append(status)
    if q:
        where.append("(o.order_id::text = %s OR u.full_name ILIKE %s OR u.email ILIKE %s)")
        params += [q.lstrip("#"), like(q), like(q)]
    where_sql = " AND ".join(where)

    with get_db().cursor() as cur:
        pager = paginate(
            cur,
            f"SELECT COUNT(*) FROM orders o JOIN users u ON u.user_id = o.user_id WHERE {where_sql};",
            params, page,
        )
        cur.execute(
            f"""
            SELECT o.order_id, o.order_date, o.status, u.full_name, u.email,
                   COALESCE(SUM(oi.quantity), 0), COALESCE(SUM(oi.quantity * oi.unit_price), 0)
            FROM orders o
            JOIN users u ON u.user_id = o.user_id
            LEFT JOIN order_items oi ON oi.order_id = o.order_id
            WHERE {where_sql}
            GROUP BY o.order_id, u.user_id
            ORDER BY o.order_id DESC
            LIMIT %s OFFSET %s;
            """,
            params + [pager["limit"], pager["offset"]],
        )
        rows = cur.fetchall()
        cur.execute("SELECT status, COUNT(*) FROM orders GROUP BY status;")
        counts = dict(cur.fetchall())

    return render_template(
        "admin/orders.html", rows=rows, status=status, q=q, pager=pager,
        counts=counts, total_all=sum(counts.values()),
    )


@bp.route("/orders/<int:order_id>")
@admin_required
def order_detail(order_id):
    with get_db().cursor() as cur:
        cur.execute(
            """
            SELECT o.order_id, o.order_date, o.status, u.user_id, u.full_name, u.email, u.phone
            FROM orders o JOIN users u ON u.user_id = o.user_id
            WHERE o.order_id = %s;
            """,
            (order_id,),
        )
        order = cur.fetchone()
        if order is None:
            abort(404)

        cur.execute(
            """
            SELECT p.product_id, p.title, s.company_name, oi.quantity, oi.unit_price
            FROM order_items oi
            JOIN products p ON p.product_id = oi.product_id
            JOIN sellers s ON s.seller_id = p.seller_id
            WHERE oi.order_id = %s ORDER BY oi.order_item_id;
            """,
            (order_id,),
        )
        items = cur.fetchall()

    total = sum(i[3] * i[4] for i in items)
    return render_template("admin/order_detail.html", order=order, items=items, total=total)


@bp.route("/orders/<int:order_id>/status", methods=["POST"])
@admin_required
def order_status(order_id):
    conn = get_db()
    with conn.cursor() as cur:
        ok, message = set_order_status(cur, order_id, request.form.get("status", ""))
    conn.commit()
    if message:
        flash(message, "success" if ok else "error")
    return back("admin.orders")




@bp.route("/products")
@admin_required
def products():
    q = request.args.get("q", "").strip()
    state = request.args.get("state", "")
    page = request.args.get("page", 1, type=int)

    where, params = ["TRUE"], []
    if q:
        where.append("(p.title ILIKE %s OR s.company_name ILIKE %s)")
        params += [like(q), like(q)]
    if state == "active":
        where.append("p.is_active")
    elif state == "hidden":
        where.append("NOT p.is_active")
    where_sql = " AND ".join(where)

    with get_db().cursor() as cur:
        pager = paginate(
            cur,
            f"SELECT COUNT(*) FROM products p JOIN sellers s ON s.seller_id = p.seller_id WHERE {where_sql};",
            params, page,
        )
        cur.execute(
            f"""
            SELECT p.product_id, p.title, s.company_name, c.name, p.price, p.stock_qty, p.is_active
            FROM products p
            JOIN sellers s ON s.seller_id = p.seller_id
            JOIN categories c ON c.category_id = p.category_id
            WHERE {where_sql}
            ORDER BY p.product_id DESC LIMIT %s OFFSET %s;
            """,
            params + [pager["limit"], pager["offset"]],
        )
        rows = cur.fetchall()

    return render_template("admin/products.html", rows=rows, q=q, state=state, pager=pager)


@bp.route("/products/<int:product_id>/toggle", methods=["POST"])
@admin_required
def product_toggle(product_id):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE products SET is_active = NOT is_active WHERE product_id = %s RETURNING title, is_active;",
            (product_id,),
        )
        row = cur.fetchone()
    if row is None:
        abort(404)
    conn.commit()
    flash(f"«{row[0]}» {'показан в каталоге' if row[1] else 'скрыт из каталога'}.", "success")
    return back("admin.products")




@bp.route("/users")
@admin_required
def users():
    q = request.args.get("q", "").strip()
    role = request.args.get("role", "")
    page = request.args.get("page", 1, type=int)

    where, params = ["TRUE"], []
    if q:
        where.append("(u.full_name ILIKE %s OR u.email ILIKE %s OR s.company_name ILIKE %s)")
        params += [like(q)] * 3
    if role in dict(ROLES):
        where.append("u.role = %s")
        params.append(role)
    where_sql = " AND ".join(where)

    with get_db().cursor() as cur:
        pager = paginate(
            cur,
            f"SELECT COUNT(*) FROM users u LEFT JOIN sellers s ON s.user_id = u.user_id WHERE {where_sql};",
            params, page,
        )
        cur.execute(
            f"""
            SELECT u.user_id, u.full_name, u.email, u.phone, u.role, u.is_active, s.company_name
            FROM users u LEFT JOIN sellers s ON s.user_id = u.user_id
            WHERE {where_sql}
            ORDER BY u.user_id DESC LIMIT %s OFFSET %s;
            """,
            params + [pager["limit"], pager["offset"]],
        )
        rows = cur.fetchall()

    return render_template("admin/users.html", rows=rows, q=q, role=role, pager=pager, roles=ROLES)


@bp.route("/users/<int:user_id>/role", methods=["POST"])
@admin_required
def user_role(user_id):
    new_role = request.form.get("role")
    if new_role not in dict(ROLES):
        abort(400)
    if user_id == current_user()["id"]:
        flash("Свою роль изменить нельзя.", "error")
        return back("admin.users")

    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET role = %s WHERE user_id = %s RETURNING full_name;", (new_role, user_id)
        )
        row = cur.fetchone()
        if row is None:
            abort(404)
        if new_role == ROLE_SELLER:
            cur.execute("SELECT 1 FROM sellers WHERE user_id = %s;", (user_id,))
            if cur.fetchone() is None:
                cur.execute(
                    """
                    INSERT INTO sellers (seller_id, company_name, contact_email, user_id)
                    SELECT %s, full_name, email, user_id FROM users WHERE user_id = %s;
                    """,
                    (next_id(cur, "sellers", "seller_id"), user_id),
                )
    conn.commit()
    flash(f"{row[0]}: роль — {dict(ROLES)[new_role]}.", "success")
    return back("admin.users")


@bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@admin_required
def user_toggle(user_id):
    if user_id == current_user()["id"]:
        flash("Себя заблокировать нельзя.", "error")
        return back("admin.users")

    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET is_active = NOT is_active WHERE user_id = %s RETURNING full_name, is_active;",
            (user_id,),
        )
        row = cur.fetchone()
        if row is None:
            abort(404)
        if not row[1]:  
            cur.execute(
                """
                UPDATE products SET is_active = FALSE
                WHERE seller_id IN (SELECT seller_id FROM sellers WHERE user_id = %s);
                """,
                (user_id,),
            )
    conn.commit()
    flash(f"{row[0]} {'разблокирован' if row[1] else 'заблокирован'}.", "success")
    return back("admin.users")



@bp.route("/categories")
@admin_required
def categories():
    with get_db().cursor() as cur:
        cur.execute(
            """
            SELECT c.category_id, c.name, c.parent_category_id,
                   (SELECT COUNT(*) FROM products p WHERE p.category_id = c.category_id),
                   (SELECT COUNT(*) FROM categories ch WHERE ch.parent_category_id = c.category_id)
            FROM categories c ORDER BY c.category_id;
            """
        )
        rows = cur.fetchall()

    nodes = {r[0]: {"id": r[0], "name": r[1], "parent_id": r[2], "products": r[3],
                    "children": r[4], "subs": []} for r in rows}
    roots = []
    for node in nodes.values():
        if node["parent_id"] in nodes:
            nodes[node["parent_id"]]["subs"].append(node)
        else:
            roots.append(node)

    return render_template("admin/categories.html", roots=roots)


@bp.route("/categories/add", methods=["POST"])
@admin_required
def category_add():
    name = request.form.get("name", "").strip()
    parent_id = request.form.get("parent_id", type=int)
    if not name or len(name) > 255:
        flash("Введите название категории.", "error")
        return redirect(url_for("admin.categories"))

    conn = get_db()
    with conn.cursor() as cur:
        if parent_id is not None:
            cur.execute("SELECT 1 FROM categories WHERE category_id = %s;", (parent_id,))
            if cur.fetchone() is None:
                abort(400)
        cur.execute(
            "INSERT INTO categories (category_id, name, parent_category_id) VALUES (%s, %s, %s);",
            (next_id(cur, "categories", "category_id"), name, parent_id),
        )
    conn.commit()
    flash(f"Категория «{name}» добавлена.", "success")
    return redirect(url_for("admin.categories"))


@bp.route("/categories/<int:category_id>/rename", methods=["POST"])
@admin_required
def category_rename(category_id):
    name = request.form.get("name", "").strip()
    if not name or len(name) > 255:
        flash("Название не может быть пустым.", "error")
        return redirect(url_for("admin.categories"))

    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("UPDATE categories SET name = %s WHERE category_id = %s;", (name, category_id))
        if cur.rowcount == 0:
            abort(404)
    conn.commit()
    flash("Название обновлено.", "success")
    return redirect(url_for("admin.categories"))


@bp.route("/categories/<int:category_id>/delete", methods=["POST"])
@admin_required
def category_delete(category_id):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT (SELECT COUNT(*) FROM products WHERE category_id = %s),
                   (SELECT COUNT(*) FROM categories WHERE parent_category_id = %s);
            """,
            (category_id, category_id),
        )
        products, children = cur.fetchone()
        if products or children:
            flash("Нельзя удалить категорию, в которой есть товары или подкатегории.", "error")
            return redirect(url_for("admin.categories"))
        cur.execute("DELETE FROM categories WHERE category_id = %s;", (category_id,))
    conn.commit()
    flash("Категория удалена.", "success")
    return redirect(url_for("admin.categories"))




@bp.route("/reviews")
@admin_required
def reviews():
    page = request.args.get("page", 1, type=int)
    with get_db().cursor() as cur:
        pager = paginate(cur, "SELECT COUNT(*) FROM reviews;", [], page)
        cur.execute(
            """
            SELECT r.review_id, u.full_name, p.product_id, p.title, r.rating, r.comment
            FROM reviews r
            JOIN users u ON u.user_id = r.user_id
            JOIN products p ON p.product_id = r.product_id
            ORDER BY r.review_id DESC LIMIT %s OFFSET %s;
            """,
            (pager["limit"], pager["offset"]),
        )
        rows = cur.fetchall()
    return render_template("admin/reviews.html", rows=rows, pager=pager)


@bp.route("/reviews/<int:review_id>/delete", methods=["POST"])
@admin_required
def review_delete(review_id):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM reviews WHERE review_id = %s;", (review_id,))
    conn.commit()
    flash("Отзыв удалён.", "success")
    return back("admin.reviews")
