"""MODULE 3 (data part): Affected areas submit requests with quantity and urgency."""
import sqlite3
import db

PRIORITY_LABELS = {1: "CRITICAL", 2: "HIGH", 3: "NORMAL"}


def add_area(name, district, disaster_type, representative, phone=None):
    try:
        with db.transaction() as c:
            cur = c.execute("INSERT INTO affected_area(name,district,disaster_type,representative,phone) "
                            "VALUES (?,?,?,?,?)", (name, district, disaster_type, representative, phone))
            return cur.lastrowid
    except sqlite3.IntegrityError as e:
        raise ValueError("Area already exists or disaster type is invalid.") from e


def list_areas():
    return db.get_conn().execute("SELECT * FROM affected_area ORDER BY area_id").fetchall()


def submit_request(area_id, resource_id, qty, priority):
    if qty <= 0:
        raise ValueError("Quantity must be positive")
    try:
        with db.transaction() as c:
            cur = c.execute("INSERT INTO resource_request(area_id,resource_id,quantity_requested,priority) "
                            "VALUES (?,?,?,?)", (area_id, resource_id, qty, priority))
            return cur.lastrowid
    except sqlite3.IntegrityError as e:
        raise ValueError("Invalid area / resource / priority") from e


def pending_requests():
    """Requests still needing stock, oldest first (arrival order)."""
    return db.get_conn().execute("""
        SELECT request_id, resource_id, priority,
               quantity_requested - quantity_fulfilled AS remaining
        FROM resource_request WHERE status <> 'FULFILLED' ORDER BY request_id""").fetchall()


def area_requests(area_id):
    return db.get_conn().execute("""
        SELECT q.request_id AS req_id, r.name AS resource, q.quantity_requested AS requested,
               q.quantity_fulfilled AS fulfilled,
               CASE q.priority WHEN 1 THEN 'CRITICAL' WHEN 2 THEN 'HIGH' ELSE 'NORMAL' END AS priority,
               q.status, q.created_at AS submitted
        FROM resource_request q JOIN resource r ON r.resource_id = q.resource_id
        WHERE q.area_id=? ORDER BY q.request_id""", (area_id,)).fetchall()
