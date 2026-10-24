"""MODULE 2: Inventory & Warehouse management.
OS concept: one MUTEX (threading.Lock) per resource. Anything that changes stock of a resource
(donation arriving, allocation leaving) must hold that resource's mutex first.
"""
import threading
import db

_locks = {}
_locks_guard = threading.Lock()   # protects the dictionary of locks itself


def get_lock(resource_id):
    with _locks_guard:
        if resource_id not in _locks:
            _locks[resource_id] = threading.Lock()
        return _locks[resource_id]


def add_warehouse(name, location):
    with db.transaction() as c:
        c.execute("INSERT INTO warehouse(name,location) VALUES (?,?)", (name, location))


def add_resource(name, unit):
    with db.transaction() as c:
        c.execute("INSERT INTO resource(name,unit) VALUES (?,?)", (name, unit))


def list_warehouses():
    return db.get_conn().execute("SELECT * FROM warehouse ORDER BY warehouse_id").fetchall()


def list_resources():
    return db.get_conn().execute("SELECT * FROM resource ORDER BY resource_id").fetchall()


def add_stock(conn, warehouse_id, resource_id, qty):
    """Upsert. Must be called inside a transaction while holding the resource mutex."""
    conn.execute("""INSERT INTO inventory(warehouse_id,resource_id,quantity) VALUES (?,?,?)
                    ON CONFLICT(warehouse_id,resource_id)
                    DO UPDATE SET quantity = quantity + excluded.quantity""",
                 (warehouse_id, resource_id, qty))


def low_stock(threshold=100):
    return db.get_conn().execute("""
        SELECT r.name AS resource, COALESCE(SUM(i.quantity),0) AS total_stock, r.unit
        FROM resource r LEFT JOIN inventory i ON i.resource_id = r.resource_id
        GROUP BY r.resource_id HAVING total_stock < ? ORDER BY total_stock""", (threshold,)).fetchall()
