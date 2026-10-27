from flask import Blueprint, render_template, request

from ..db import get_db

bp = Blueprint("catalog", __name__)


def escape_like(value):
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def fetch_categories(cur):
    cur.execute(
        "SELECT category_id, name, parent_category_id FROM categories ORDER BY category_id;"
    )
    return cur.fetchall()


def fetch_products(cur, search):
    query = """
        SELECT p.product_id, p.title, p.price, p.stock_qty, p.category_id, s.company_name
        FROM products p
        JOIN sellers s ON s.seller_id = p.seller_id
        WHERE p.is_active
    """
    params = ()

    if search:
        query += " AND p.title ILIKE %s"
        params = (f"%{escape_like(search)}%",)

    cur.execute(query + " ORDER BY p.product_id;", params)
    return cur.fetchall()


def build_category_tree(categories, products, hide_empty=False):
    nodes = {
        category_id: {
            "id": category_id,
            "name": name,
            "parent_id": parent_id,
            "subcategories": [],
            "products": [],
        }
        for category_id, name, parent_id in categories
    }

    for product_id, title, price, stock_qty, category_id, seller in products:
        if category_id in nodes:
            nodes[category_id]["products"].append(
                {
                    "id": product_id,
                    "title": title,
                    "price": price,
                    "stock_qty": stock_qty,
                    "seller": seller,
                }
            )

    roots = []
    for node in nodes.values():
        if node["parent_id"] is None:
            roots.append(node)
        elif node["parent_id"] in nodes:
            nodes[node["parent_id"]]["subcategories"].append(node)

    if hide_empty:  # при поиске показываем только то, где что-то нашлось
        for root in roots:
            root["subcategories"] = [s for s in root["subcategories"] if s["products"]]
        roots = [r for r in roots if r["products"] or r["subcategories"]]

    return roots


@bp.route("/")
def home():
    search = request.args.get("search", "").strip()

    with get_db().cursor() as cur:
        categories = fetch_categories(cur)
        products = fetch_products(cur, search)

    return render_template(
        "index.html",
        root_categories=build_category_tree(categories, products, hide_empty=bool(search)),
        search=search,
        found=len(products),
    )
