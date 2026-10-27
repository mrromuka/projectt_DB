"""Рекомендации: что предложить покупателю, когда он взял товар.

Как это работает (простыми словами)
-----------------------------------
Мы берём товары, которые человек положил в корзину (или смотрит), и ищем,
что ему ещё может пригодиться. Ищем по трём правилам, строго по порядку.
Как только набралось нужное число товаров (по умолчанию 4) — останавливаемся.

  1. «Часто берут вместе».
     Смотрим на чужие прошлые заказы: если в тех же заказах, где был этот
     товар, часто встречался другой — предлагаем его. Чем больше таких
     заказов, тем выше он в списке. Отменённые заказы не считаем.
     Пример: с телефоном часто покупают чехол.

  2. «Из той же категории».
     Если «вместе покупают» не хватило (магазин новый, заказов мало),
     добавляем товары из той же категории. Сначала с лучшим средним рейтингом
     по отзывам, потом самые продаваемые.

  3. «Популярное».
     Если и этого мало, добавляем то, что магазин вообще чаще всего покупает.

Что никогда не рекомендуем:
  * то, что уже лежит в корзине (или смотрим прямо сейчас);
  * скрытые товары и товары, которых нет в наличии.

Рекомендации не пропадают после покупки: когда корзина пустая, мы опираемся
на то, что человек недавно заказал (последние 3 заказа), а если истории ещё нет —
показываем просто популярное.

Каждая рекомендация получает «причину» (reason) — короткую подпись,
которую видит покупатель, например «Часто берут вместе».
"""

from .constants import STATUS_CANCELLED

DEFAULT_LIMIT = 4

REASON_TOGETHER = "Часто берут вместе"
REASON_CATEGORY = "Из той же категории"
REASON_POPULAR = "Популярное"


def _together(cur, product_ids, exclude_ids, limit):
    """Правило 1: товары из тех же заказов."""
    cur.execute(
        """
        SELECT other.product_id
        FROM order_items mine
        JOIN orders o ON o.order_id = mine.order_id AND o.status <> %(cancelled)s
        JOIN order_items other ON other.order_id = o.order_id
        JOIN products p ON p.product_id = other.product_id
        WHERE mine.product_id = ANY(%(ids)s::int[])
          AND p.is_active AND p.stock_qty > 0
          AND p.product_id <> ALL(%(exclude)s::int[])
        GROUP BY other.product_id
        ORDER BY COUNT(DISTINCT o.order_id) DESC, other.product_id
        LIMIT %(limit)s;
        """,
        {"cancelled": STATUS_CANCELLED, "ids": product_ids, "exclude": exclude_ids, "limit": limit},
    )
    return [row[0] for row in cur.fetchall()]


def _same_category(cur, product_ids, exclude_ids, limit):
    """Правило 2: та же категория, лучшие по рейтингу и продажам."""
    cur.execute(
        """
        SELECT p.product_id
        FROM products p
        LEFT JOIN (
            SELECT product_id, AVG(rating) AS avg_rating
            FROM reviews GROUP BY product_id
        ) r ON r.product_id = p.product_id
        LEFT JOIN (
            SELECT oi.product_id, SUM(oi.quantity) AS sold
            FROM order_items oi JOIN orders o ON o.order_id = oi.order_id
            WHERE o.status <> %(cancelled)s
            GROUP BY oi.product_id
        ) s ON s.product_id = p.product_id
        WHERE p.is_active AND p.stock_qty > 0
          AND p.category_id IN (
              SELECT category_id FROM products WHERE product_id = ANY(%(ids)s::int[])
          )
          AND p.product_id <> ALL(%(exclude)s::int[])
        ORDER BY r.avg_rating DESC NULLS LAST, s.sold DESC NULLS LAST, p.product_id
        LIMIT %(limit)s;
        """,
        {"cancelled": STATUS_CANCELLED, "ids": product_ids, "exclude": exclude_ids, "limit": limit},
    )
    return [row[0] for row in cur.fetchall()]


def _popular(cur, exclude_ids, limit):
    """Правило 3: самое покупаемое в магазине."""
    cur.execute(
        """
        SELECT p.product_id
        FROM products p
        LEFT JOIN (
            SELECT oi.product_id, SUM(oi.quantity) AS sold
            FROM order_items oi JOIN orders o ON o.order_id = oi.order_id
            WHERE o.status <> %(cancelled)s
            GROUP BY oi.product_id
        ) s ON s.product_id = p.product_id
        WHERE p.is_active AND p.stock_qty > 0
          AND p.product_id <> ALL(%(exclude)s::int[])
        ORDER BY s.sold DESC NULLS LAST, p.product_id
        LIMIT %(limit)s;
        """,
        {"cancelled": STATUS_CANCELLED, "exclude": exclude_ids, "limit": limit},
    )
    return [row[0] for row in cur.fetchall()]


def _load_cards(cur, ids):
    """Подробности о товарах (название, цена, продавец, рейтинг) по списку id."""
    if not ids:
        return {}
    cur.execute(
        """
        SELECT p.product_id, p.title, p.price, p.stock_qty, s.company_name,
               (SELECT ROUND(AVG(rating), 1) FROM reviews r WHERE r.product_id = p.product_id)
        FROM products p JOIN sellers s ON s.seller_id = p.seller_id
        WHERE p.product_id = ANY(%s::int[]);
        """,
        (ids,),
    )
    return {
        row[0]: {
            "id": row[0],
            "title": row[1],
            "price": row[2],
            "stock_qty": row[3],
            "seller": row[4],
            "rating": row[5],
        }
        for row in cur.fetchall()
    }


RECENT_ORDERS = 3  # сколько последних заказов учитываем


def recent_purchase_ids(cur, user_id, orders=RECENT_ORDERS):
    """Товары из последних заказов покупателя (кроме отменённых)."""
    cur.execute(
        """
        SELECT DISTINCT oi.product_id
        FROM order_items oi
        WHERE oi.order_id IN (
            SELECT order_id FROM orders
            WHERE user_id = %s AND status <> %s
            ORDER BY order_id DESC
            LIMIT %s
        );
        """,
        (user_id, STATUS_CANCELLED, orders),
    )
    return [row[0] for row in cur.fetchall()]


def get_user_recommendations(cur, user_id, cart_ids=(), limit=DEFAULT_LIMIT):
    """Рекомендации «для человека»: по корзине И по недавним покупкам.

    Работает и когда корзина пустая (например, сразу после оформления заказа).
    """
    seed = list(dict.fromkeys([*cart_ids, *recent_purchase_ids(cur, user_id)]))
    return get_recommendations(cur, seed, limit)


def get_recommendations(cur, product_ids, limit=DEFAULT_LIMIT):
    """Возвращает список карточек товаров для рекомендации.

    product_ids — товары, к которым подбираем (корзина или текущий товар).
    Каждая карточка: id, title, price, stock_qty, seller, rating, reason.
    """
    product_ids = list(product_ids)
    # Если подбирать не к чему (новый покупатель) — правила 1 и 2 ничего не найдут,
    # и сработает «Популярное».

    exclude = list(product_ids)  # уже выбранные и «свои» товары не повторяем
    picked = []  # [(id, причина)]

    steps = (
        (REASON_TOGETHER, lambda n: _together(cur, product_ids, exclude, n)),
        (REASON_CATEGORY, lambda n: _same_category(cur, product_ids, exclude, n)),
        (REASON_POPULAR, lambda n: _popular(cur, exclude, n)),
    )
    for reason, find in steps:
        missing = limit - len(picked)
        if missing <= 0:
            break
        for product_id in find(missing):
            picked.append((product_id, reason))
            exclude.append(product_id)

    cards = _load_cards(cur, [pid for pid, _ in picked])
    return [{**cards[pid], "reason": reason} for pid, reason in picked if pid in cards]
