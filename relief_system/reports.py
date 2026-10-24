"""MODULE 4 (reporting part): reports built on SQL views and aggregate queries."""
import db


def print_table(title, rows):
    print(f"\n=== {title} ===")
    if not rows:
        print("  (no records)")
        return
    headers = list(rows[0].keys())
    data = [[("" if r[h] is None else str(r[h])) for h in headers] for r in rows]
    widths = [max(len(h), *(len(row[i]) for row in data)) for i, h in enumerate(headers)]
    line = "  ".join(h.upper().ljust(w) for h, w in zip(headers, widths))
    print(line)
    print("-" * len(line))
    for row in data:
        print("  ".join(v.ljust(w) for v, w in zip(row, widths)))


def q(sql, params=()):
    return db.get_conn().execute(sql, params).fetchall()


def inventory_report():
    print_table("AVAILABLE INVENTORY (per warehouse)", q("SELECT * FROM v_inventory ORDER BY resource, warehouse"))
    print_table("TOTAL STOCK (all warehouses)", q("""
        SELECT r.name AS resource, COALESCE(SUM(i.quantity),0) AS total, r.unit
        FROM resource r LEFT JOIN inventory i ON i.resource_id=r.resource_id
        GROUP BY r.resource_id ORDER BY r.name"""))


def pending_report():
    print_table("PENDING REQUIREMENTS", q("""SELECT * FROM v_pending_requests
        ORDER BY CASE priority WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 ELSE 3 END, req_id"""))


def donation_report(donor_id=None):
    if donor_id:
        print_table("MY DONATION HISTORY", q(
            "SELECT id,resource,quantity,warehouse,date FROM v_donation_history WHERE donor_id=? ORDER BY id",
            (donor_id,)))
    else:
        print_table("DONATION HISTORY", q("SELECT * FROM v_donation_history ORDER BY id"))
        print_table("DONOR-WISE TOTALS", q("""
            SELECT o.name AS donor, o.donor_type AS type, COUNT(d.donation_id) AS donations,
                   COALESCE(SUM(d.quantity),0) AS total_items
            FROM donor o LEFT JOIN donation d ON d.donor_id=o.donor_id
            GROUP BY o.donor_id ORDER BY total_items DESC"""))


def distribution_report():
    print_table("DISTRIBUTION HISTORY", q("SELECT * FROM v_distribution_history ORDER BY id"))


def integrity_check():
    """Proof of correctness: for every resource, donated == in stock + distributed."""
    rows = q("""
        SELECT r.name AS resource,
          COALESCE((SELECT SUM(quantity) FROM donation     WHERE resource_id=r.resource_id),0) AS donated,
          COALESCE((SELECT SUM(quantity) FROM inventory    WHERE resource_id=r.resource_id),0) AS in_stock,
          COALESCE((SELECT SUM(quantity) FROM distribution WHERE resource_id=r.resource_id),0) AS distributed
        FROM resource r ORDER BY r.name""")
    out, ok = [], True
    for r in rows:
        good = r["donated"] == r["in_stock"] + r["distributed"]
        ok &= good
        out.append({"resource": r["resource"], "donated": r["donated"], "in_stock": r["in_stock"],
                    "distributed": r["distributed"], "balanced": "OK" if good else "MISMATCH"})
    print_table("INTEGRITY CHECK  (donated = in stock + distributed)", out)
    return ok


def summary_report():
    s = q("""SELECT (SELECT COUNT(*) FROM donor) AS donors,
                    (SELECT COUNT(*) FROM donation) AS donations,
                    (SELECT COUNT(*) FROM affected_area) AS areas,
                    (SELECT COUNT(*) FROM resource_request) AS requests,
                    (SELECT COUNT(*) FROM resource_request WHERE status='FULFILLED') AS fulfilled,
                    (SELECT COUNT(*) FROM resource_request WHERE status<>'FULFILLED') AS open_requests""")
    print_table("SYSTEM SUMMARY", s)
    integrity_check()
