from decimal import Decimal, InvalidOperation
from math import ceil

from .constants import PER_PAGE, STATUS_CANCELLED, STATUS_LABELS


def paginate(cur, count_sql, params, page):
    cur.execute(count_sql, params)
    total = cur.fetchone()[0]
    pages = max(1, ceil(total / PER_PAGE))
    page = min(max(page, 1), pages)
    return {
        "page": page,
        "pages": pages,
        "total": total,
        "limit": PER_PAGE,
        "offset": (page - 1) * PER_PAGE,
    }


def category_choices(cur):
    """[(id, 'Родитель › Категория')] для выпадающих списков."""
    cur.execute(
        """
        SELECT c.category_id,
               CASE WHEN p.name IS NULL THEN c.name ELSE p.name || ' › ' || c.name END AS label
        FROM categories c
        LEFT JOIN categories p ON p.category_id = c.parent_category_id
        ORDER BY label;
        """
    )
    return cur.fetchall()


def set_order_status(cur, order_id, new_status):
    """Меняет статус заказа. При отмене возвращает товары на склад.
    Возвращает (успех, сообщение)."""
    if new_status not in STATUS_LABELS:
        return False, "Неизвестный статус."

    cur.execute("SELECT status FROM orders WHERE order_id = %s FOR UPDATE;", (order_id,))
    row = cur.fetchone()
    if row is None:
        return False, "Заказ не найден."

    old_status = row[0]
    if old_status == new_status:
        return True, None
    if old_status == STATUS_CANCELLED:
        return False, "Отменённый заказ нельзя вернуть в работу — оформите новый."

    cur.execute("UPDATE orders SET status = %s WHERE order_id = %s;", (new_status, order_id))

    if new_status == STATUS_CANCELLED:
        cur.execute(
            """
            UPDATE products p SET stock_qty = p.stock_qty + oi.quantity
            FROM order_items oi
            WHERE oi.order_id = %s AND oi.product_id = p.product_id;
            """,
            (order_id,),
        )

    return True, f"Заказ №{order_id}: статус «{STATUS_LABELS[new_status]}»."


def parse_product_form(form, valid_category_ids):
    """Проверяет форму товара. Возвращает (данные, список_ошибок)."""
    errors = []
    title = form.get("title", "").strip()
    if not title:
        errors.append("Введите название товара.")
    elif len(title) > 255:
        errors.append("Название слишком длинное (максимум 255 символов).")

    price = None
    try:
        price = Decimal(form.get("price", "").strip().replace(",", ".").replace(" ", ""))
        if not price.is_finite() or price <= 0 or price >= Decimal("100000000"):
            raise InvalidOperation
        price = price.quantize(Decimal("0.01"))
    except InvalidOperation:
        errors.append("Цена должна быть положительным числом.")

    stock = form.get("stock_qty", type=int)
    if stock is None or not 0 <= stock <= 1_000_000:
        errors.append("Количество на складе — целое число от 0.")

    category_id = form.get("category_id", type=int)
    if category_id not in valid_category_ids:
        errors.append("Выберите категорию.")

    data = {"title": title, "price": price, "stock_qty": stock, "category_id": category_id}
    return data, errors
