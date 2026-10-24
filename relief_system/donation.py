"""MODULE 1: Donation & Donor management."""
import sqlite3
import db
import inventory


def register_donor(name, donor_type, phone, email=None):
    """Returns new donor_id. The UNIQUE phone constraint rejects duplicate donors."""
    try:
        with db.transaction() as c:
            cur = c.execute("INSERT INTO donor(name,donor_type,phone,email) VALUES (?,?,?,?)",
                            (name, donor_type, phone, email))
            return cur.lastrowid
    except sqlite3.IntegrityError as e:
        raise ValueError("Donor already registered with this phone number "
                         "(or invalid donor type).") from e


def record_donation(donor_id, resource_id, warehouse_id, qty):
    """One atomic transaction: (1) insert donation row, (2) increase warehouse stock.
    Both succeed or both are rolled back. The resource mutex stops a concurrent
    allocation from reading half-updated stock."""
    if qty <= 0:
        raise ValueError("Quantity must be positive")
    with inventory.get_lock(resource_id):
        try:
            with db.transaction() as c:
                c.execute("INSERT INTO donation(donor_id,resource_id,warehouse_id,quantity) "
                          "VALUES (?,?,?,?)", (donor_id, resource_id, warehouse_id, qty))
                inventory.add_stock(c, warehouse_id, resource_id, qty)
        except sqlite3.IntegrityError as e:
            raise ValueError("Invalid donor / resource / warehouse ID") from e


def list_donors():
    return db.get_conn().execute("SELECT donor_id,name,donor_type,phone FROM donor").fetchall()
