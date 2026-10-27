from . import account, admin, cart, catalog, orders, reviews, seller


def register_blueprints(app):
    for module in (catalog, account, cart, orders, reviews, seller, admin):
        app.register_blueprint(module.bp)
