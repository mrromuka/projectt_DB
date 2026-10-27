from flask import Blueprint, abort, redirect, render_template, request, url_for

from ..auth import current_user_id, login_required
from ..db import get_db, next_id
from ..recommendations import get_recommendations

bp = Blueprint("reviews", __name__)

MIN_RATING = 1
MAX_RATING = 5


@bp.route("/reviews/<int:product_id>")
def show(product_id):
    with get_db().cursor() as cur:
        cur.execute(
            """
            SELECT p.title, p.price, s.company_name
            FROM products p JOIN sellers s ON s.seller_id = p.seller_id
            WHERE p.product_id = %s;
            """,
            (product_id,),
        )
        product = cur.fetchone()
        if product is None:
            abort(404)

        cur.execute(
            """
            SELECT r.review_id, u.full_name, r.rating, r.comment
            FROM reviews r
            JOIN users u ON r.user_id = u.user_id
            WHERE r.product_id = %s
            ORDER BY r.review_id DESC;
            """,
            (product_id,),
        )
        reviews = [
            {"review_id": review_id, "full_name": full_name, "rating": rating, "comment": comment}
            for review_id, full_name, rating, comment in cur.fetchall()
        ]

        similar = get_recommendations(cur, [product_id])

    average = round(sum(r["rating"] for r in reviews) / len(reviews), 1) if reviews else None
    product = {"title": product[0], "price": product[1], "seller": product[2]}

    return render_template(
        "reviews.html", reviews=reviews,
        product_id=product_id,
        product=product,
        average=average,
        similar=similar,
    )


@bp.route("/review/<int:product_id>", methods=["POST"])
@login_required
def add(product_id):
    rating = request.form.get("rating", type=int)
    comment = request.form.get("comment", "").strip()

    if rating is None or not MIN_RATING <= rating <= MAX_RATING or not comment:
        abort(400)

    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM products WHERE product_id = %s;", (product_id,))
        if cur.fetchone() is None:
            abort(404)
        cur.execute(
            """
            INSERT INTO reviews (review_id, user_id, product_id, rating, comment)
            VALUES (%s, %s, %s, %s, %s);
            """,
            (next_id(cur, "reviews", "review_id"), current_user_id(), product_id, rating, comment[:1000]),
        )
    conn.commit()

    return redirect(url_for("reviews.show", product_id=product_id))
