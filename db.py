"""Database layer (DBMS side).
- One SQLite connection per thread (connections must not be shared between threads).
- transaction() gives ACID behaviour: COMMIT on success, ROLLBACK on any error.
"""
import os
import sqlite3
import threading
from contextlib import contextmanager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "relief.db")
_local = threading.local()


def use_database(path):
    """Point the system at another database file (used by the demo)."""
    global DB_PATH
    close_conn()
    DB_PATH = path


def close_conn():
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def get_conn():
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)  # manual transactions
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        _local.conn = conn
    return conn


@contextmanager
def transaction():
    """BEGIN IMMEDIATE takes the write lock up-front, so two writers can't interleave."""
    conn = get_conn()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def init_db():
    with open(os.path.join(BASE_DIR, "schema.sql"), encoding="utf-8") as f:
        get_conn().executescript(f.read())
