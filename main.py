"""Relief Resource Collection and Distribution Management System  -  Void Century Coders
Run:  python main.py
Logins (sample data):  admin/admin123   staff/staff123   donor1/donor123   area1/area123
"""
import sqlite3

import allocation
import auth
import db
import donation
import inventory
import reports
import resource_request as rr
import scheduler
import seed


# ---------------- small input helpers ----------------
def ask(prompt):
    return input(prompt).strip()


def ask_int(prompt, valid=None):
    while True:
        s = ask(prompt)
        if s.lstrip("-").isdigit():
            n = int(s)
            if valid is None or n in valid:
                return n
        print("  Invalid input, try again.")


def pick(title, rows, label):
    """Show a numbered list of DB rows and return the chosen id (first column)."""
    print(f"\n{title}")
    ids = []
    for r in rows:
        ids.append(r[0])
        print(f"  {r[0]}. {label(r)}")
    return ask_int("Choose ID: ", ids)


def pick_priority():
    print("\nUrgency:  1=CRITICAL  2=HIGH  3=NORMAL")
    return ask_int("Choose 1-3: ", [1, 2, 3])


def safe(fn):
    """Run an action; show friendly errors instead of crashing in front of the examiner."""
    try:
        fn()
    except (ValueError, sqlite3.Error) as e:
        print(f"  ! Error: {e}")


# ---------------- shared actions ----------------
def do_dispatch():
    results = allocation.run_dispatch(workers=4, docks=2)
    reports.print_table("ALLOCATION RESULT", [
        {"req": f"R{r['request_id']}", "resource": r["resource"], "needed": r["needed"],
         "allocated": r["allocated"], "status": r["status"]} for r in results])


def do_schedule_sim():
    procs = [scheduler.Proc(r["request_id"], r["priority"], i, scheduler.burst_for(r["remaining"]))
             for i, r in enumerate(rr.pending_requests())]
    scheduler.report(procs)


def do_record_donation(donor_id=None):
    if donor_id is None:
        donor_id = pick("Donors:", donation.list_donors(), lambda r: f"{r['name']} ({r['donor_type']})")
    res = pick("Resources:", inventory.list_resources(), lambda r: f"{r['name']} ({r['unit']})")
    wh = pick("Warehouses:", inventory.list_warehouses(), lambda r: f"{r['name']} - {r['location']}")
    qty = ask_int("Quantity: ")
    donation.record_donation(donor_id, res, wh, qty)
    print("  Donation recorded and stock updated.")


def do_submit_request(area_id=None):
    if area_id is None:
        area_id = pick("Areas:", rr.list_areas(), lambda r: f"{r['name']} ({r['disaster_type']})")
    res = pick("Resources:", inventory.list_resources(), lambda r: f"{r['name']} ({r['unit']})")
    qty = ask_int("Quantity required: ")
    prio = pick_priority()
    rid = rr.submit_request(area_id, res, qty, prio)
    print(f"  Request R{rid} submitted ({rr.PRIORITY_LABELS[prio]}).")


def do_low_stock():
    reports.print_table("LOW STOCK ALERT (< 100 units)", inventory.low_stock(100))


# ---------------- role menus ----------------
def admin_menu(user):
    def add_wh(): inventory.add_warehouse(ask("Warehouse name: "), ask("Location: ")); print("  Added.")
    def add_res(): inventory.add_resource(ask("Resource name: "), ask("Unit (e.g. packets): ")); print("  Added.")
    def add_area():
        rr.add_area(ask("Area name: "), ask("District: "),
                    ask("Disaster (Flood/Earthquake/Cyclone/Landslide/Drought/Other): ").title(),
                    ask("Representative name: "), ask("Phone: ")); print("  Area registered.")
    def add_user():
        role = ask("Role (STAFF/AREA_REP/DONOR/ADMIN): ").upper()
        ref = None
        if role == "AREA_REP":
            ref = pick("Areas:", rr.list_areas(), lambda r: r["name"])
        elif role == "DONOR":
            ref = pick("Donors:", donation.list_donors(), lambda r: r["name"])
        auth.create_user(ask("Username: "), ask("Password: "), role, ref); print("  User created.")
    def load_sample(): print(f"  {seed.sample_requests()} sample requests submitted.")

    actions = {
        "1": ("Inventory report", reports.inventory_report),
        "2": ("Pending requirements", reports.pending_report),
        "3": ("Donation history", reports.donation_report),
        "4": ("Distribution history", reports.distribution_report),
        "5": ("System summary + integrity check", reports.summary_report),
        "6": ("RUN ALLOCATION (multithreaded priority dispatch)", do_dispatch),
        "7": ("Scheduling simulation (FCFS vs Priority vs Aging)", do_schedule_sim),
        "8": ("Record a donation", do_record_donation),
        "9": ("Add warehouse", add_wh),
        "10": ("Add resource type", add_res),
        "11": ("Register affected area", add_area),
        "12": ("Create user account", add_user),
        "13": ("Load sample requests (demo data)", load_sample),
        "14": ("Low-stock alert", do_low_stock),
    }
    run_menu(f"ADMIN MENU ({user['username']})", actions)


def staff_menu(user):
    actions = {
        "1": ("Inventory report", reports.inventory_report),
        "2": ("Low-stock alert", do_low_stock),
        "3": ("Receive a donation into warehouse", do_record_donation),
        "4": ("Pending requirements", reports.pending_report),
        "5": ("RUN ALLOCATION (multithreaded priority dispatch)", do_dispatch),
        "6": ("Distribution history", reports.distribution_report),
    }
    run_menu(f"RELIEF STAFF MENU ({user['username']})", actions)


def donor_menu(user):
    did = user["ref_id"]
    actions = {
        "1": ("Make a donation", lambda: do_record_donation(did)),
        "2": ("My donation history", lambda: reports.donation_report(did)),
    }
    run_menu(f"DONOR MENU ({user['username']})", actions)


def area_menu(user):
    aid = user["ref_id"]
    actions = {
        "1": ("Submit resource request", lambda: do_submit_request(aid)),
        "2": ("My requests & status", lambda: reports.print_table("MY REQUESTS", rr.area_requests(aid))),
    }
    run_menu(f"AREA REPRESENTATIVE MENU ({user['username']})", actions)


def run_menu(title, actions):
    while True:
        print(f"\n===== {title} =====")
        for k, (label, _) in actions.items():
            print(f"  {k:>2}. {label}")
        print("   0. Logout")
        choice = ask("Select: ")
        if choice == "0":
            return
        if choice in actions:
            safe(actions[choice][1])
        else:
            print("  Invalid option.")


MENUS = {"ADMIN": admin_menu, "STAFF": staff_menu, "DONOR": donor_menu, "AREA_REP": area_menu}


def register_donor_account():
    name = ask("Your / organisation name: ")
    dtype = "NGO" if ask("Type - 1=Individual 2=NGO: ") == "2" else "Individual"
    did = donation.register_donor(name, dtype, ask("Phone (unique): "), ask("Email (optional): ") or None)
    auth.create_user(ask("Choose username: "), ask("Choose password: "), "DONOR", did)
    print("  Registered! You can now log in.")


def main():
    db.init_db()
    if seed.seed_if_empty():
        print("First run: sample data loaded.")
    while True:
        print("\n######  RELIEF RESOURCE MANAGEMENT SYSTEM  ######\n  1. Login\n  2. Register as donor\n  0. Exit")
        c = ask("Select: ")
        if c == "0":
            break
        if c == "1":
            user = auth.login(ask("Username: "), ask("Password: "))
            if user:
                MENUS[user["role"]](user)
            else:
                print("  Wrong username or password.")
        elif c == "2":
            safe(register_donor_account)


if __name__ == "__main__":
    main()
