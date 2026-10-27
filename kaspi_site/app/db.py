import psycopg2
from flask import current_app, g
from psycopg2 import sql


def get_db():
    if "db" not in g:
        config = current_app.config
        g.db = psycopg2.connect(
            host=config["DB_HOST"],
            port=config["DB_PORT"],
            dbname=config["DB_NAME"],
            user=config["DB_USER"],
            password=config["DB_PASSWORD"],
        )
    return g.db


def close_db(error=None):
    conn = g.pop("db", None)
    if conn is None:
        return
    if error is not None:
        conn.rollback()
    conn.close()


def next_id(cur, table, column):
    cur.execute(
        sql.SQL("SELECT COALESCE(MAX({column}), 0) + 1 FROM {table};").format(
            column=sql.Identifier(column),
            table=sql.Identifier(table),
        )
    )
    return cur.fetchone()[0]


def init_app(app):
    app.teardown_appcontext(close_db)
