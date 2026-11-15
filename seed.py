"""Sample data so the system is usable (and demo-able) immediately."""
import auth
import db
import donation
import inventory
import resource_request as rr


def _id(table, col, name):
    return db.get_conn().execute(f"SELECT rowid FROM {table} WHERE {col}=?", (name,)).fetchone()[0]


def seed_if_empty():
    if db.get_conn().execute("SELECT COUNT(*) FROM warehouse").fetchone()[0]:
        return False
    inventory.add_warehouse("Central Warehouse", "Delhi")
    inventory.add_warehouse("Regional Warehouse", "Lucknow")
    for n, u in [("Food Packets", "packets"), ("Drinking Water", "litres"), ("Medicine Kits", "kits"),
                 ("Clothes", "sets"), ("Blankets", "pieces")]:
        inventory.add_resource(n, u)
    for a in [("Riverside Village", "Sitapur", "Flood", "Ramesh Kumar", "9000000001"),
              ("Hill Town", "Almora", "Landslide", "Sunita Devi", "9000000002"),
              ("Coastal Colony", "Puri", "Cyclone", "Arjun Das", "9000000003"),
              ("Old City Ward", "Bhuj", "Earthquake", "Fatima Khan", "9000000004")]:
        rr.add_area(*a)
    d1 = donation.register_donor("Rahul Sharma", "Individual", "9111111111", "rahul@example.com")
    d2 = donation.register_donor("Helping Hands Trust", "NGO", "9222222222", "info@helpinghands.org")
    d3 = donation.register_donor("Priya Verma", "Individual", "9333333333")
    donation.record_donation(d1, 1, 1, 300)   # Food, Central
    donation.record_donation(d2, 1, 2, 200)   # Food, Regional
    donation.record_donation(d2, 2, 1, 500)   # Water
    donation.record_donation(d3, 2, 2, 300)
    donation.record_donation(d2, 3, 1, 120)   # Medicine
    donation.record_donation(d1, 4, 2, 300)   # Clothes
    donation.record_donation(d3, 5, 1, 250)   # Blankets
    auth.create_user("admin", "admin123", "ADMIN")
    auth.create_user("staff", "staff123", "STAFF")
    auth.create_user("donor1", "donor123", "DONOR", d1)
    auth.create_user("area1", "area123", "AREA_REP", 1)
    return True


def sample_requests():
    """Deliberately more demand than stock for Food and Medicine, so priority matters."""
    A = lambda n: _id("affected_area", "name", n)
    R = lambda n: _id("resource", "name", n)
    data = [("Coastal Colony", "Food Packets", 300, 3),     # NORMAL, arrives first
            ("Hill Town", "Medicine Kits", 60, 3),          # NORMAL, arrives first
            ("Riverside Village", "Food Packets", 250, 1),  # CRITICAL
            ("Old City Ward", "Drinking Water", 300, 3),
            ("Hill Town", "Medicine Kits", 100, 1),         # CRITICAL
            ("Old City Ward", "Blankets", 150, 1),
            ("Coastal Colony", "Drinking Water", 400, 2),
            ("Riverside Village", "Clothes", 100, 3),
            ("Old City Ward", "Food Packets", 200, 2)]      # HIGH
    for area, res, qty, pr in data:
        rr.submit_request(A(area), R(res), qty, pr)
    return len(data)
