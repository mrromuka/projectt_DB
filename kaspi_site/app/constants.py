ROLE_BUYER = "buyer"
ROLE_SELLER = "seller"
ROLE_ADMIN = "admin"

ROLES = [
    (ROLE_BUYER, "Покупатель"),
    (ROLE_SELLER, "Продавец"),
    (ROLE_ADMIN, "Администратор"),
]

STATUS_NEW = "new"
STATUS_CANCELLED = "cancelled"

# (значение в БД, подпись на сайте)
ORDER_STATUSES = [
    ("new", "Новый"),
    ("processing", "В обработке"),
    ("shipped", "Отправлен"),
    ("delivered", "Доставлен"),
    ("cancelled", "Отменён"),
]

ROLE_LABELS = dict(ROLES)
STATUS_LABELS = dict(ORDER_STATUSES)

PER_PAGE = 20
