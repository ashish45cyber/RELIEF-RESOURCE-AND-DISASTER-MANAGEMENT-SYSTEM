"""Tkinter GUI for the Relief Resource Management System.   Run:  python gui.py
It is only a front-end: all DBMS/OS logic is in the same modules the terminal version uses.
Important OS point: the allocation runs in BACKGROUND threads and reports back through a
thread-safe queue.Queue, so the window never freezes while worker threads are busy."""
import contextlib
import io
import queue
import sqlite3
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import allocation
import auth
import db
import donation
import inventory
import resource_request as rr
import scheduler
import seed

BG = "#f4f6f8"
ACCENT = "#1f4e79"
PRIORITY_COLORS = {"CRITICAL": "#f8c9c9", "HIGH": "#fde6c0", "NORMAL": "#e3f0e3"}


# ------------------------------------------------------------------ helpers
def query(sql, params=()):
    cur = db.get_conn().execute(sql, params)
    cols = [d[0] for d in cur.description]
    return cols, cur.fetchall()


def cid(text):
    """'3 - Food Packets' -> 3"""
    if not text:
        raise ValueError("Please select an item from the list.")
    return int(text.split(" - ")[0])


def guard(fn):
    """Show errors in a dialog instead of crashing."""
    try:
        return fn()
    except (ValueError, sqlite3.Error) as e:
        messagebox.showerror("Error", str(e))


def to_int(text, field="Quantity"):
    text = text.strip()
    if not text.isdigit() or int(text) <= 0:
        raise ValueError(f"{field} must be a positive whole number.")
    return int(text)


class Table(ttk.Frame):
    """Treeview that fills itself from an SQL query (or from rows you give it)."""

    def __init__(self, parent, sql=None, params=(), height=8):
        super().__init__(parent)
        self.sql, self.params = sql, params
        self.tree = ttk.Treeview(self, show="headings", height=height)
        sy = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        sx = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        for name, color in PRIORITY_COLORS.items():
            self.tree.tag_configure(name, background=color)
        self.tree.tag_configure("bad", background="#f5a3a3")
        self.natural = {}
        self.tree.bind("<Configure>", lambda e: self.fit())

    def fit(self):
        """Give every column its natural width, then share any spare space evenly."""
        cols = self.tree["columns"]
        if not cols:
            return
        spare = self.tree.winfo_width() - sum(self.natural[c] for c in cols) - 4
        extra = max(0, spare // len(cols))
        for c in cols:
            self.tree.column(c, width=self.natural[c] + extra, stretch=False)

    def show(self, cols, rows):
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = cols
        for i, c in enumerate(cols):
            self.tree.heading(c, text=c.replace("_", " ").upper())
            longest = max([len(str(r[i])) for r in rows if r[i] is not None] + [0])
            self.natural[c] = max(len(c) * 9, longest * 8) + 24
            self.tree.column(c, width=self.natural[c], anchor="w", stretch=False)
        for r in rows:
            vals = [("" if v is None else v) for v in r]
            tags = [str(v) for v in vals if v in PRIORITY_COLORS or v == "MISMATCH"]
            tags = ["bad" if t == "MISMATCH" else t for t in tags]
            self.tree.insert("", "end", values=vals, tags=tags)
        self.after_idle(self.fit)

    def refresh(self):
        if self.sql:
            cols, rows = query(self.sql, self.params)
            self.show(cols, rows)


class Picker(ttk.Frame):
    """Label + dropdown filled with 'id - name' strings from a loader function."""

    def __init__(self, parent, label, loader):
        super().__init__(parent)
        self.loader = loader
        ttk.Label(self, text=label, width=16).pack(side="left")
        self.var = tk.StringVar()
        self.combo = ttk.Combobox(self, textvariable=self.var, state="readonly", width=38)
        self.combo.pack(side="left")
        self.reload()

    def reload(self):
        values = self.loader()
        self.combo["values"] = values
        if self.var.get() not in values:
            self.var.set(values[0] if values else "")

    def get(self):
        return cid(self.var.get())


class Field(ttk.Frame):
    def __init__(self, parent, label, show=None, width=40):
        super().__init__(parent)
        ttk.Label(self, text=label, width=16).pack(side="left")
        self.var = tk.StringVar()
        ttk.Entry(self, textvariable=self.var, show=show, width=width).pack(side="left")

    def get(self):
        return self.var.get().strip()

    def clear(self):
        self.var.set("")


# loaders for dropdowns
def load_resources():
    return [f"{r['resource_id']} - {r['name']} ({r['unit']})" for r in inventory.list_resources()]


def load_warehouses():
    return [f"{r['warehouse_id']} - {r['name']} ({r['location']})" for r in inventory.list_warehouses()]


def load_donors():
    return [f"{r['donor_id']} - {r['name']} ({r['donor_type']})" for r in donation.list_donors()]


def load_areas():
    return [f"{r['area_id']} - {r['name']} ({r['disaster_type']})" for r in rr.list_areas()]


# ------------------------------------------------------------------ tabs
class BaseTab(ttk.Frame):
    def __init__(self, app):
        super().__init__(app.notebook, padding=8)
        self.app = app

    def refresh(self):
        pass


class SectionsTab(BaseTab):
    """A tab that just stacks one or more SQL-backed tables."""

    def __init__(self, app, sections):
        super().__init__(app)
        self.tables = []
        for i, (title, sql, params) in enumerate(sections):
            ttk.Label(self, text=title, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(6, 2))
            t = Table(self, sql, params, height=8 if len(sections) == 1 else 6)
            t.pack(fill="both", expand=True)
            self.tables.append(t)

    def refresh(self):
        for t in self.tables:
            t.refresh()


PENDING_SQL = ("SELECT * FROM v_pending_requests ORDER BY CASE priority WHEN 'CRITICAL' THEN 1 "
               "WHEN 'HIGH' THEN 2 ELSE 3 END, req_id")
INTEGRITY_SQL = """
SELECT resource, donated, in_stock, distributed,
       CASE WHEN donated = in_stock + distributed THEN 'OK' ELSE 'MISMATCH' END AS balanced
FROM (SELECT r.name AS resource,
        COALESCE((SELECT SUM(quantity) FROM donation     WHERE resource_id=r.resource_id),0) AS donated,
        COALESCE((SELECT SUM(quantity) FROM inventory    WHERE resource_id=r.resource_id),0) AS in_stock,
        COALESCE((SELECT SUM(quantity) FROM distribution WHERE resource_id=r.resource_id),0) AS distributed
      FROM resource r ORDER BY r.name)"""


class DashboardTab(BaseTab):
    def __init__(self, app):
        super().__init__(app)
        self.cards = {}
        row = ttk.Frame(self)
        row.pack(fill="x")
        for key in ("Donors", "Donations", "Areas", "Requests", "Fulfilled", "Open"):
            f = tk.Frame(row, bg="white", highlightbackground="#c9d3dd", highlightthickness=1)
            f.pack(side="left", expand=True, fill="x", padx=4, pady=4)
            v = tk.Label(f, text="0", font=("Segoe UI", 20, "bold"), bg="white", fg=ACCENT)
            v.pack(pady=(8, 0))
            tk.Label(f, text=key, bg="white", fg="#555").pack(pady=(0, 8))
            self.cards[key] = v
        ttk.Label(self, text="Integrity check  (donated = in stock + distributed)",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(10, 2))
        self.integrity = Table(self, INTEGRITY_SQL, height=6)
        self.integrity.pack(fill="both", expand=True)
        ttk.Label(self, text="Low-stock alert (< 100 units total)",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(10, 2))
        self.low = Table(self, height=4)
        self.low.pack(fill="both", expand=True)

    def refresh(self):
        _, rows = query("""SELECT (SELECT COUNT(*) FROM donor), (SELECT COUNT(*) FROM donation),
            (SELECT COUNT(*) FROM affected_area), (SELECT COUNT(*) FROM resource_request),
            (SELECT COUNT(*) FROM resource_request WHERE status='FULFILLED'),
            (SELECT COUNT(*) FROM resource_request WHERE status<>'FULFILLED')""")
        for key, val in zip(self.cards, rows[0]):
            self.cards[key].config(text=str(val))
        self.integrity.refresh()
        low = inventory.low_stock(100)
        self.low.show(["resource", "total_stock", "unit"], [tuple(r) for r in low])


class DonateTab(BaseTab):
    def __init__(self, app, donor_id=None):
        super().__init__(app)
        self.donor_id = donor_id
        box = ttk.LabelFrame(self, text="Record a donation", padding=10)
        box.pack(anchor="w", fill="x")
        self.pickers = []
        if donor_id is None:
            self.donor = Picker(box, "Donor", load_donors)
            self.donor.pack(anchor="w", pady=3)
            self.pickers.append(self.donor)
        self.res = Picker(box, "Resource", load_resources)
        self.wh = Picker(box, "Warehouse", load_warehouses)
        self.qty = Field(box, "Quantity", width=12)
        for w in (self.res, self.wh, self.qty):
            w.pack(anchor="w", pady=3)
        self.pickers += [self.res, self.wh]
        ttk.Button(box, text="Submit donation", command=self.submit).pack(anchor="w", pady=8)
        ttk.Label(self, text="Donation history", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(10, 2))
        if donor_id is None:
            self.hist = Table(self, "SELECT * FROM v_donation_history ORDER BY id DESC")
        else:
            self.hist = Table(self, "SELECT id,resource,quantity,warehouse,date FROM v_donation_history "
                                    "WHERE donor_id=? ORDER BY id DESC", (donor_id,))
        self.hist.pack(fill="both", expand=True)

    def submit(self):
        def go():
            did = self.donor_id if self.donor_id is not None else self.donor.get()
            donation.record_donation(did, self.res.get(), self.wh.get(), to_int(self.qty.get()))
            self.qty.clear()
            messagebox.showinfo("Done", "Donation recorded and warehouse stock updated.")
            self.app.refresh_all()
        guard(go)

    def refresh(self):
        for p in self.pickers:
            p.reload()
        self.hist.refresh()


class RequestTab(BaseTab):
    def __init__(self, app, area_id=None):
        super().__init__(app)
        self.area_id = area_id
        box = ttk.LabelFrame(self, text="Submit a resource request", padding=10)
        box.pack(anchor="w", fill="x")
        self.pickers = []
        if area_id is None:
            self.area = Picker(box, "Affected area", load_areas)
            self.area.pack(anchor="w", pady=3)
            self.pickers.append(self.area)
        self.res = Picker(box, "Resource", load_resources)
        self.res.pack(anchor="w", pady=3)
        self.pickers.append(self.res)
        self.qty = Field(box, "Quantity", width=12)
        self.qty.pack(anchor="w", pady=3)
        pr = ttk.Frame(box)
        pr.pack(anchor="w", pady=3)
        ttk.Label(pr, text="Urgency", width=16).pack(side="left")
        self.prio = tk.IntVar(value=3)
        for val, txt in ((1, "CRITICAL"), (2, "HIGH"), (3, "NORMAL")):
            ttk.Radiobutton(pr, text=txt, value=val, variable=self.prio).pack(side="left", padx=6)
        ttk.Button(box, text="Submit request", command=self.submit).pack(anchor="w", pady=8)
        ttk.Label(self, text="Requests and their status", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(10, 2))
        if area_id is None:
            self.hist = Table(self, "SELECT q.request_id AS req_id, a.name AS area, r.name AS resource, "
                                    "q.quantity_requested AS requested, q.quantity_fulfilled AS fulfilled, "
                                    "CASE q.priority WHEN 1 THEN 'CRITICAL' WHEN 2 THEN 'HIGH' ELSE 'NORMAL' END AS priority, "
                                    "q.status FROM resource_request q JOIN affected_area a ON a.area_id=q.area_id "
                                    "JOIN resource r ON r.resource_id=q.resource_id ORDER BY q.request_id DESC")
        else:
            self.hist = Table(self, "SELECT q.request_id AS req_id, r.name AS resource, "
                                    "q.quantity_requested AS requested, q.quantity_fulfilled AS fulfilled, "
                                    "CASE q.priority WHEN 1 THEN 'CRITICAL' WHEN 2 THEN 'HIGH' ELSE 'NORMAL' END AS priority, "
                                    "q.status, q.created_at AS submitted FROM resource_request q "
                                    "JOIN resource r ON r.resource_id=q.resource_id WHERE q.area_id=? "
                                    "ORDER BY q.request_id DESC", (area_id,))
        self.hist.pack(fill="both", expand=True)

    def submit(self):
        def go():
            aid = self.area_id if self.area_id is not None else self.area.get()
            rid = rr.submit_request(aid, self.res.get(), to_int(self.qty.get()), self.prio.get())
            self.qty.clear()
            messagebox.showinfo("Done", f"Request R{rid} submitted.")
            self.app.refresh_all()
        guard(go)

    def refresh(self):
        for p in self.pickers:
            p.reload()
        self.hist.refresh()


class DispatchTab(BaseTab):
    """Runs the multithreaded priority dispatcher in the background."""

    def __init__(self, app):
        super().__init__(app)
        self.log_q = queue.Queue()          # thread-safe channel: worker threads -> GUI thread
        self.running = False
        ttk.Label(self, text="Pending requests (served top to bottom: priority, then arrival)",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.pending = Table(self, PENDING_SQL, height=5)
        self.pending.pack(fill="x")

        ctl = ttk.Frame(self)
        ctl.pack(fill="x", pady=8)
        ttk.Label(ctl, text="Worker threads:").pack(side="left")
        self.workers = tk.Spinbox(ctl, from_=1, to=8, width=3)
        self.workers.delete(0, "end"); self.workers.insert(0, "4")
        self.workers.pack(side="left", padx=(4, 14))
        ttk.Label(ctl, text="Loading docks (semaphore):").pack(side="left")
        self.docks = tk.Spinbox(ctl, from_=1, to=8, width=3)
        self.docks.delete(0, "end"); self.docks.insert(0, "2")
        self.docks.pack(side="left", padx=(4, 14))
        self.btn = ttk.Button(ctl, text="RUN ALLOCATION", command=self.start)
        self.btn.pack(side="left")
        self.status = ttk.Label(ctl, text="Idle")
        self.status.pack(side="left", padx=12)

        pan = ttk.Frame(self)
        pan.pack(fill="both", expand=True)
        pan.columnconfigure(0, weight=11, uniform="c")
        pan.columnconfigure(1, weight=9, uniform="c")
        pan.rowconfigure(0, weight=1)
        left = ttk.Frame(pan); right = ttk.Frame(pan)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        right.grid(row=0, column=1, sticky="nsew")
        ttk.Label(left, text="Live thread log", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.log = ScrolledText(left, height=10, font=("Consolas", 9), state="disabled")
        self.log.pack(fill="both", expand=True)
        ttk.Label(right, text="Result", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.result = Table(right, height=8)
        self.result.pack(fill="both", expand=True)
        self.after(100, self.poll)

    def write(self, text):
        self.log.config(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def start(self):
        if self.running:
            return
        try:
            w, d = int(self.workers.get()), int(self.docks.get())
            if not (1 <= w <= 8 and 1 <= d <= 8):
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Workers and docks must be numbers between 1 and 8.")
            return
        self.running = True
        self.btn.config(state="disabled")
        self.status.config(text="Running...")
        self.log.config(state="normal"); self.log.delete("1.0", "end"); self.log.config(state="disabled")
        threading.Thread(target=self.controller, args=(w, d), daemon=True).start()

    def controller(self, workers, docks):
        """Background thread: starts the worker pool, then reports the results to the GUI."""
        try:
            results = allocation.run_dispatch(workers=workers, docks=docks, work_seconds=0.4,
                                              log=lambda m: self.log_q.put(("log", m)))
            self.log_q.put(("done", results))
        except Exception as e:                       # never leave the button disabled
            self.log_q.put(("log", f"ERROR: {e}"))
            self.log_q.put(("done", []))
        finally:
            db.close_conn()

    def poll(self):
        """Runs in the GUI thread every 100 ms and drains the queue."""
        try:
            while True:
                kind, payload = self.log_q.get_nowait()
                if kind == "log":
                    self.write(payload)
                else:
                    cols = ["req", "resource", "needed", "allocated", "status"]
                    self.result.show(cols, [(f"R{r['request_id']}", r["resource"], r["needed"],
                                             r["allocated"], r["status"]) for r in payload])
                    self.running = False
                    self.btn.config(state="normal")
                    self.status.config(text="Finished")
                    self.app.refresh_all()
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def refresh(self):
        self.pending.refresh()


class SchedTab(BaseTab):
    def __init__(self, app):
        super().__init__(app)
        bar = ttk.Frame(self)
        bar.pack(fill="x")
        ttk.Button(bar, text="Simulate scheduling on current pending requests", command=self.run).pack(side="left")
        ttk.Label(bar, text="  FCFS vs Priority vs Priority + Aging (Gantt charts, waiting times)").pack(side="left")
        self.out = ScrolledText(self, font=("Consolas", 10), height=25)
        self.out.pack(fill="both", expand=True, pady=8)

    def run(self):
        procs = [scheduler.Proc(r["request_id"], r["priority"], i, scheduler.burst_for(r["remaining"]))
                 for i, r in enumerate(rr.pending_requests())]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            scheduler.report(procs)
        self.out.delete("1.0", "end")
        self.out.insert("end", buf.getvalue())


class ManageTab(BaseTab):
    def __init__(self, app):
        super().__init__(app)
        top = ttk.Frame(self); top.pack(fill="x")
        left = ttk.Frame(top); left.pack(side="left", fill="x", expand=True, anchor="n")
        right = ttk.Frame(top); right.pack(side="left", fill="x", expand=True, anchor="n")

        w = ttk.LabelFrame(left, text="Add warehouse", padding=8); w.pack(fill="x", pady=4)
        self.w_name, self.w_loc = Field(w, "Name", width=28), Field(w, "Location", width=28)
        self.w_name.pack(anchor="w"); self.w_loc.pack(anchor="w")
        ttk.Button(w, text="Add", command=lambda: guard(self.add_wh)).pack(anchor="w", pady=4)

        r = ttk.LabelFrame(left, text="Add resource type", padding=8); r.pack(fill="x", pady=4)
        self.r_name, self.r_unit = Field(r, "Name", width=28), Field(r, "Unit", width=28)
        self.r_name.pack(anchor="w"); self.r_unit.pack(anchor="w")
        ttk.Button(r, text="Add", command=lambda: guard(self.add_res)).pack(anchor="w", pady=4)

        a = ttk.LabelFrame(left, text="Register affected area", padding=8); a.pack(fill="x", pady=4)
        self.a_name, self.a_dist = Field(a, "Area name", width=28), Field(a, "District", width=28)
        self.a_rep, self.a_phone = Field(a, "Representative", width=28), Field(a, "Phone", width=28)
        dz = ttk.Frame(a)
        ttk.Label(dz, text="Disaster", width=16).pack(side="left")
        self.a_type = ttk.Combobox(dz, values=["Flood", "Earthquake", "Cyclone", "Landslide", "Drought", "Other"],
                                   state="readonly", width=26)
        self.a_type.current(0); self.a_type.pack(side="left")
        for f in (self.a_name, self.a_dist, dz, self.a_rep, self.a_phone):
            f.pack(anchor="w")
        ttk.Button(a, text="Register", command=lambda: guard(self.add_area)).pack(anchor="w", pady=4)

        u = ttk.LabelFrame(right, text="Create user account", padding=8); u.pack(fill="x", pady=4)
        self.u_name, self.u_pass = Field(u, "Username", width=28), Field(u, "Password", show="*", width=28)
        self.u_name.pack(anchor="w"); self.u_pass.pack(anchor="w")
        rz = ttk.Frame(u)
        ttk.Label(rz, text="Role", width=16).pack(side="left")
        self.u_role = ttk.Combobox(rz, values=["STAFF", "AREA_REP", "DONOR", "ADMIN"], state="readonly", width=26)
        self.u_role.current(0); self.u_role.pack(side="left"); rz.pack(anchor="w", pady=2)
        self.u_role.bind("<<ComboboxSelected>>", lambda e: self.reload_ref())
        self.u_ref = Picker(u, "Linked to", lambda: self.ref_values())
        self.u_ref.pack(anchor="w")
        ttk.Button(u, text="Create", command=lambda: guard(self.add_user)).pack(anchor="w", pady=4)

        s = ttk.LabelFrame(right, text="Demo data", padding=8); s.pack(fill="x", pady=4)
        ttk.Label(s, text="Adds 9 sample requests (more demand than stock\nfor Food and Medicine, so priority matters).").pack(anchor="w")
        ttk.Button(s, text="Load sample requests", command=lambda: guard(self.load_sample)).pack(anchor="w", pady=4)

    def ref_values(self):
        role = self.u_role.get() if hasattr(self, "u_role") else "STAFF"
        if role == "AREA_REP":
            return load_areas()
        if role == "DONOR":
            return load_donors()
        return []

    def reload_ref(self):
        self.u_ref.reload()
        self.u_ref.var.set(self.u_ref.combo["values"][0] if self.u_ref.combo["values"] else "")

    def add_wh(self):
        inventory.add_warehouse(self.w_name.get(), self.w_loc.get())
        self.w_name.clear(); self.w_loc.clear(); self.done("Warehouse added.")

    def add_res(self):
        inventory.add_resource(self.r_name.get(), self.r_unit.get())
        self.r_name.clear(); self.r_unit.clear(); self.done("Resource added.")

    def add_area(self):
        rr.add_area(self.a_name.get(), self.a_dist.get(), self.a_type.get(), self.a_rep.get(), self.a_phone.get())
        for f in (self.a_name, self.a_dist, self.a_rep, self.a_phone):
            f.clear()
        self.done("Area registered.")

    def add_user(self):
        role = self.u_role.get()
        ref = cid(self.u_ref.var.get()) if role in ("AREA_REP", "DONOR") else None
        auth.create_user(self.u_name.get(), self.u_pass.get(), role, ref)
        self.u_name.clear(); self.u_pass.clear(); self.done("User created.")

    def load_sample(self):
        n = seed.sample_requests()
        self.done(f"{n} sample requests submitted.")

    def done(self, msg):
        messagebox.showinfo("Done", msg)
        self.app.refresh_all()

    def refresh(self):
        self.u_ref.reload()


# ------------------------------------------------------------------ application
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Relief Resource Management System - Void Century Coders")
        self.geometry("1100x720")
        self.minsize(900, 600)
        self.configure(bg=BG)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabelframe", background=BG)
        style.configure("TLabelframe.Label", background=BG, foreground=ACCENT, font=("Segoe UI", 10, "bold"))
        style.configure("TLabel", background=BG)
        style.configure("TRadiobutton", background=BG)
        style.configure("TButton", padding=6)
        style.configure("Treeview", rowheight=24)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        db.init_db()
        seed.seed_if_empty()
        self.user, self.tabs, self.notebook = None, [], None
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.show_login()

    def clear(self):
        for w in self.winfo_children():
            w.destroy()

    # ---- login screen
    def show_login(self):
        self.clear()
        self.user = None
        outer = ttk.Frame(self); outer.pack(expand=True)
        tk.Label(outer, text="Relief Resource Collection\nand Distribution Management System",
                 font=("Segoe UI", 20, "bold"), fg=ACCENT, bg=BG).pack(pady=(0, 4))
        tk.Label(outer, text="Void Century Coders  |  DBMS + Operating Systems project",
                 fg="#555", bg=BG).pack(pady=(0, 18))
        box = ttk.LabelFrame(outer, text="Login", padding=14); box.pack()
        self.f_user, self.f_pass = Field(box, "Username", width=26), Field(box, "Password", show="*", width=26)
        self.f_user.pack(pady=3); self.f_pass.pack(pady=3)
        self.f_pass.winfo_children()[1].bind("<Return>", lambda e: self.do_login())
        row = ttk.Frame(box); row.pack(pady=8)
        ttk.Button(row, text="Login", command=self.do_login).pack(side="left", padx=4)
        ttk.Button(row, text="Register as donor", command=self.register_dialog).pack(side="left", padx=4)
        tk.Label(outer, text="Sample logins:  admin/admin123   staff/staff123   donor1/donor123   area1/area123",
                 fg="#777", bg=BG).pack(pady=14)

    def do_login(self):
        user = auth.login(self.f_user.get(), self.f_pass.get())
        if not user:
            messagebox.showerror("Login failed", "Wrong username or password.")
            return
        self.show_main(user)

    def register_dialog(self):
        win = tk.Toplevel(self); win.title("Register as donor"); win.configure(bg=BG); win.grab_set()
        body = ttk.Frame(win, padding=14); body.pack()
        name, phone = Field(body, "Name / organisation", width=28), Field(body, "Phone (unique)", width=28)
        email, uname = Field(body, "Email (optional)", width=28), Field(body, "Username", width=28)
        pw = Field(body, "Password", show="*", width=28)
        tz = ttk.Frame(body)
        ttk.Label(tz, text="Type", width=16).pack(side="left")
        dtype = ttk.Combobox(tz, values=["Individual", "NGO"], state="readonly", width=26)
        dtype.current(0); dtype.pack(side="left")
        for w in (name, tz, phone, email, uname, pw):
            w.pack(anchor="w", pady=3)

        def go():
            did = donation.register_donor(name.get(), dtype.get(), phone.get(), email.get() or None)
            auth.create_user(uname.get(), pw.get(), "DONOR", did)
            messagebox.showinfo("Registered", "Registered! You can now log in.", parent=win)
            win.destroy()
        ttk.Button(body, text="Register", command=lambda: guard(go)).pack(pady=8)

    # ---- main screen
    def show_main(self, user):
        self.clear()
        self.user, self.tabs = user, []
        bar = tk.Frame(self, bg=ACCENT); bar.pack(fill="x")
        tk.Label(bar, text=f"  {user['username']}   |   role: {user['role']}", fg="white", bg=ACCENT,
                 font=("Segoe UI", 11, "bold")).pack(side="left", pady=8)
        ttk.Button(bar, text="Logout", command=self.show_login).pack(side="right", padx=8, pady=4)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=6, pady=6)
        self.notebook.bind("<<NotebookTabChanged>>", lambda e: self.refresh_current())

        inv = ("Inventory", [("Stock per warehouse", "SELECT * FROM v_inventory ORDER BY resource, warehouse", ()),
                             ("Total stock", "SELECT r.name AS resource, COALESCE(SUM(i.quantity),0) AS total, r.unit "
                                             "FROM resource r LEFT JOIN inventory i ON i.resource_id=r.resource_id "
                                             "GROUP BY r.resource_id ORDER BY r.name", ())])
        pend = ("Pending requirements", [("Pending requests (CRITICAL first)", PENDING_SQL, ())])
        dist = ("Distribution history", [("What went where, when and how much",
                                          "SELECT * FROM v_distribution_history ORDER BY id DESC", ())])
        role = user["role"]
        if role == "ADMIN":
            plan = [("Dashboard", DashboardTab(self)), self.sec(*inv), self.sec(*pend),
                    ("Donations", DonateTab(self)), ("Requests", RequestTab(self)),
                    ("Run Allocation", DispatchTab(self)), ("Scheduling", SchedTab(self)),
                    self.sec(*dist), ("Manage", ManageTab(self))]
        elif role == "STAFF":
            plan = [("Dashboard", DashboardTab(self)), self.sec(*inv), ("Receive Donation", DonateTab(self)),
                    self.sec(*pend), ("Run Allocation", DispatchTab(self)), self.sec(*dist)]
        elif role == "DONOR":
            plan = [("Donate / My History", DonateTab(self, donor_id=user["ref_id"]))]
        else:
            plan = [("My Requests", RequestTab(self, area_id=user["ref_id"]))]
        for title, tab in plan:
            self.notebook.add(tab, text=f"  {title}  ")
            self.tabs.append(tab)
        self.refresh_all()

    def sec(self, title, sections):
        return title, SectionsTab(self, sections)

    def refresh_current(self):
        if self.notebook and self.notebook.tabs():
            idx = self.notebook.index(self.notebook.select())
            self.tabs[idx].refresh()

    def refresh_all(self):
        for t in self.tabs:
            t.refresh()


if __name__ == "__main__":
    App().mainloop()
