"""Relief Resource Management System - GUI (pure Python + Tkinter, no other languages/libraries).
Run:  python gui.py

It is only a front-end: every piece of DBMS/OS logic lives in the same modules the terminal
version uses (donation.py, inventory.py, scheduler.py, allocation.py ...).
Important OS point: allocation runs in BACKGROUND threads and talks to the window through a
thread-safe queue.Queue, so the window never freezes while worker threads are busy.
"""
import csv
import queue
import sqlite3
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, ttk

import allocation
import auth
import db
import donation
import inventory
import resource_request as rr
import scheduler
import seed

# ------------------------------------------------------------------ look & feel
FONT = "Segoe UI"
BG, CARD, BORDER = "#eef2f7", "#ffffff", "#dbe3ec"
SIDEBAR, SIDE_HOVER, SIDE_ACTIVE = "#0f2a43", "#173a5c", "#1e4d7b"
ACCENT, ACCENT_D = "#2563eb", "#1d4ed8"
GREEN, GREEN_D = "#16a34a", "#15803d"
AMBER, RED, RED_D = "#d97706", "#dc2626", "#b91c1c"
PURPLE, TEAL = "#7c3aed", "#0d9488"
TEXT, MUTED, HEAD = "#1f2937", "#6b7280", "#0f2a43"

PRI_NAME = {1: "CRITICAL", 2: "HIGH", 3: "NORMAL"}
PRI_COLOR = {"CRITICAL": "#ef4444", "HIGH": "#f59e0b", "NORMAL": "#3b82f6"}
# row tint (background, text) used in tables
ROW_TAGS = {
    "CRITICAL": ("#fee2e2", "#991b1b"), "HIGH": ("#ffedd5", "#9a3412"), "NORMAL": ("#e0f2fe", "#075985"),
    "FULFILLED": ("#dcfce7", "#166534"), "PARTIAL": ("#fef3c7", "#92400e"), "PENDING": ("#f1f5f9", "#475569"),
    "MISMATCH": ("#fca5a5", "#7f1d1d"),
}


def setup_styles(root):
    s = ttk.Style(root)
    s.theme_use("clam")
    root.option_add("*TCombobox*Listbox.font", (FONT, 10))
    s.configure("M.TEntry", fieldbackground="white", foreground=TEXT, bordercolor=BORDER,
                lightcolor=BORDER, darkcolor=BORDER, padding=6)
    s.map("M.TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)],
          darkcolor=[("focus", ACCENT)])
    s.configure("M.TSpinbox", fieldbackground="white", foreground=TEXT, bordercolor=BORDER,
                lightcolor=BORDER, darkcolor=BORDER, arrowcolor=MUTED, padding=4)
    s.configure("M.TCombobox", fieldbackground="white", background="white", foreground=TEXT,
                bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, arrowcolor=MUTED, padding=5)
    s.map("M.TCombobox", fieldbackground=[("readonly", "white")], bordercolor=[("focus", ACCENT)])

    def button(name, bg, hover, fg="white", border=None):
        border = border or bg
        s.configure(name, background=bg, foreground=fg, bordercolor=border, lightcolor=bg, darkcolor=bg,
                    focuscolor=bg, padding=(16, 8), font=(FONT, 10, "bold"), relief="flat")
        s.map(name, background=[("disabled", "#cbd5e1"), ("active", hover)],
              foreground=[("disabled", "#94a3b8")], lightcolor=[("active", hover)],
              darkcolor=[("active", hover)], bordercolor=[("active", hover if border == bg else ACCENT)])
    button("Primary.TButton", ACCENT, ACCENT_D)
    button("Success.TButton", GREEN, GREEN_D)
    button("Danger.TButton", RED, RED_D)
    button("Ghost.TButton", "white", "#eff6ff", fg=ACCENT, border=BORDER)
    s.configure("Ghost.TButton", padding=(10, 5), font=(FONT, 9, "bold"))

    s.configure("Treeview", background="white", fieldbackground="white", foreground=TEXT,
                rowheight=30, borderwidth=0, font=(FONT, 10))
    s.configure("Treeview.Heading", background="#e8eef6", foreground=HEAD, font=(FONT, 9, "bold"),
                relief="flat", padding=(8, 7), borderwidth=0)
    s.map("Treeview.Heading", background=[("active", "#d6e3f2")])
    s.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "white")])
    s.configure("Vertical.TScrollbar", background="#c7d0db", troughcolor="#f1f5f9", bordercolor="#f1f5f9",
                arrowcolor=MUTED, relief="flat")
    s.configure("Horizontal.TScrollbar", background="#c7d0db", troughcolor="#f1f5f9", bordercolor="#f1f5f9",
                arrowcolor=MUTED, relief="flat")
    s.configure("Accent.Horizontal.TProgressbar", troughcolor="#e5e7eb", background=ACCENT,
                bordercolor="#e5e7eb", lightcolor=ACCENT, darkcolor=ACCENT, thickness=14)


# ------------------------------------------------------------------ small helpers
def query(sql, params=()):
    cur = db.get_conn().execute(sql, params)
    return [d[0] for d in cur.description], cur.fetchall()


def cid(text):
    """'3 - Food Packets' -> 3"""
    if not text:
        raise ValueError("Please select an item from the list.")
    return int(text.split(" - ")[0])


def to_int(text, field="Quantity"):
    text = text.strip()
    if not text.isdigit() or int(text) <= 0:
        raise ValueError(f"{field} must be a positive whole number.")
    return int(text)


def lerp_color(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def load_resources():
    return [f"{r['resource_id']} - {r['name']} ({r['unit']})" for r in inventory.list_resources()]


def load_warehouses():
    return [f"{r['warehouse_id']} - {r['name']} ({r['location']})" for r in inventory.list_warehouses()]


def load_donors():
    return [f"{r['donor_id']} - {r['name']} ({r['donor_type']})" for r in donation.list_donors()]


def load_areas():
    return [f"{r['area_id']} - {r['name']} ({r['disaster_type']})" for r in rr.list_areas()]


# ------------------------------------------------------------------ reusable widgets
class Card(tk.Frame):
    """White rounded-look panel with an optional title. Put your widgets in card.body."""

    def __init__(self, parent, title=None, pad=14):
        super().__init__(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        self.head = None
        if title:
            self.head = tk.Frame(self, bg=CARD)
            self.head.pack(fill="x", padx=pad, pady=(10, 0))
            tk.Label(self.head, text=title, bg=CARD, fg=HEAD, font=(FONT, 11, "bold")).pack(side="left")
            tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=pad, pady=(8, 0))
        self.body = tk.Frame(self, bg=CARD)
        self.body.pack(fill="both", expand=True, padx=pad, pady=pad)


class StatCard(tk.Frame):
    def __init__(self, parent, label, color):
        super().__init__(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        tk.Frame(self, bg=color, width=5).pack(side="left", fill="y")
        body = tk.Frame(self, bg=CARD)
        body.pack(side="left", fill="both", expand=True, padx=14, pady=10)
        self.value = tk.Label(body, text="0", font=(FONT, 22, "bold"), bg=CARD, fg=color)
        self.value.pack(anchor="w")
        tk.Label(body, text=label, font=(FONT, 9), bg=CARD, fg=MUTED).pack(anchor="w")

    def set(self, v):
        self.value.config(text=str(v))


class Field(tk.Frame):
    def __init__(self, parent, label, show=None, width=30):
        super().__init__(parent, bg=CARD)
        tk.Label(self, text=label, bg=CARD, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
        self.var = tk.StringVar()
        self.entry = ttk.Entry(self, textvariable=self.var, show=show, style="M.TEntry", width=width)
        self.entry.pack(fill="x", pady=(2, 8))

    def get(self):
        return self.var.get().strip()

    def clear(self):
        self.var.set("")


class Picker(tk.Frame):
    """Dropdown filled with 'id - name' strings produced by a loader function."""

    def __init__(self, parent, label, loader, width=30):
        super().__init__(parent, bg=CARD)
        self.loader = loader
        tk.Label(self, text=label, bg=CARD, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
        self.var = tk.StringVar()
        self.combo = ttk.Combobox(self, textvariable=self.var, state="readonly", style="M.TCombobox", width=width)
        self.combo.pack(fill="x", pady=(2, 8))
        self.reload()

    def reload(self):
        values = self.loader()
        self.combo["values"] = values
        if self.var.get() not in values:
            self.var.set(values[0] if values else "")

    def get(self):
        return cid(self.var.get())


class Segmented(tk.Frame):
    """Coloured toggle buttons (used for the urgency selector)."""

    def __init__(self, parent, label, options, default):
        super().__init__(parent, bg=CARD)
        tk.Label(self, text=label, bg=CARD, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
        row = tk.Frame(self, bg=CARD)
        row.pack(anchor="w", pady=(2, 8))
        self.value, self.options, self.labels = default, options, {}
        for val, text, color in options:
            lb = tk.Label(row, text=text, font=(FONT, 9, "bold"), padx=14, pady=7, cursor="hand2")
            lb.pack(side="left", padx=(0, 6))
            lb.bind("<Button-1>", lambda e, v=val: self.set(v))
            self.labels[val] = lb
        self.set(default)

    def set(self, value):
        self.value = value
        for val, text, color in self.options:
            if val == value:
                self.labels[val].config(bg=color, fg="white")
            else:
                self.labels[val].config(bg="#eef2f7", fg=MUTED)

    def get(self):
        return self.value


class Table(tk.Frame):
    """Styled data grid: striped rows, click-to-sort headers, search box, CSV export.
    Fills itself from an SQL query (call refresh()) or from rows you pass to show()."""

    def __init__(self, parent, sql=None, params=(), height=8, search=True, export=True):
        super().__init__(parent, bg=CARD)
        self.sql, self.params = sql, params
        self.cols, self.rows, self.shown, self.natural = [], [], [], {}
        self.sort_col, self.sort_rev = None, False
        self.query = tk.StringVar()
        self.query.trace_add("write", lambda *a: self.render())
        if search or export:
            bar = tk.Frame(self, bg=CARD)
            bar.pack(fill="x", pady=(0, 8))
            if search:
                tk.Label(bar, text="Search", bg=CARD, fg=MUTED, font=(FONT, 9)).pack(side="left", padx=(0, 6))
                ttk.Entry(bar, textvariable=self.query, style="M.TEntry", width=24).pack(side="left")
            self.count = tk.Label(bar, text="", bg=CARD, fg=MUTED, font=(FONT, 9))
            self.count.pack(side="left", padx=12)
            if export:
                ttk.Button(bar, text="Export CSV", style="Ghost.TButton", command=self.export).pack(side="right")
        else:
            self.count = tk.Label(self)
        wrap = tk.Frame(self, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        wrap.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(wrap, show="headings", height=height)
        sy = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        sx = ttk.Scrollbar(wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        self.tree.tag_configure("odd", background="white")
        self.tree.tag_configure("even", background="#f8fafc")
        for name, (bg, fg) in ROW_TAGS.items():
            self.tree.tag_configure(name, background=bg, foreground=fg)
        self.empty = tk.Label(wrap, text="No records to show", bg="white", fg=MUTED, font=(FONT, 10))
        self.tree.bind("<Configure>", lambda e: self.fit())

    # ---- data
    def show(self, cols, rows):
        self.cols = list(cols)
        self.rows = [tuple(r) for r in rows]
        self.tree["columns"] = self.cols
        for i, c in enumerate(self.cols):
            longest = max([len(str(r[i])) for r in self.rows if r[i] is not None] + [0])
            self.natural[c] = max(len(c) * 8 + 30, int(longest * 7.2) + 24)
            self.tree.column(c, width=self.natural[c], anchor="w", stretch=False)
        self.render()
        self.after_idle(self.fit)

    def refresh(self):
        if self.sql:
            cols, rows = query(self.sql, self.params)
            self.show(cols, rows)

    @staticmethod
    def _key(v):
        try:
            return (0, float(v), "")
        except (TypeError, ValueError):
            return (1, 0.0, str(v).lower())

    def _tag(self, row, n):
        d = dict(zip(self.cols, row))
        p = str(d.get("priority", "")).upper()
        if p in ROW_TAGS:
            return p
        st = str(d.get("status", d.get("balanced", ""))).upper()
        if st in ROW_TAGS:
            return st
        return "even" if n % 2 else "odd"

    def render(self):
        needle = self.query.get().strip().lower()
        rows = [r for r in self.rows if not needle or any(needle in str(v).lower() for v in r)]
        if self.sort_col in self.cols:
            i = self.cols.index(self.sort_col)
            rows.sort(key=lambda r: self._key(r[i]), reverse=self.sort_rev)
        self.tree.delete(*self.tree.get_children())
        for n, r in enumerate(rows):
            self.tree.insert("", "end", values=["" if v is None else v for v in r], tags=(self._tag(r, n),))
        self.shown = rows
        total = len(self.rows)
        self.count.config(text=f"{len(rows)} of {total} rows" if needle else f"{total} rows")
        for c in self.cols:
            arrow = ("  \u25b2" if not self.sort_rev else "  \u25bc") if c == self.sort_col else ""
            self.tree.heading(c, text=c.replace("_", " ").upper() + arrow, anchor="w",
                              command=lambda c=c: self.sort_by(c))
        if rows:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.55, anchor="center")

    def sort_by(self, col):
        self.sort_rev = (not self.sort_rev) if col == self.sort_col else False
        self.sort_col = col
        self.render()

    def fit(self):
        """Natural column widths, then share any spare width evenly."""
        if not self.cols:
            return
        avail = self.tree.winfo_width() - 4
        if avail < 50:
            return
        total = sum(self.natural[c] for c in self.cols)
        if total <= avail:                       # spare room: share it evenly
            extra = (avail - total) // len(self.cols)
            widths = {c: self.natural[c] + extra for c in self.cols}
        else:                                    # too wide: shrink instead of scrolling sideways
            factor = avail / total
            widths = {c: max(64, int(self.natural[c] * factor)) for c in self.cols}
        for c in self.cols:
            self.tree.column(c, width=widths[c], stretch=False)

    def export(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV file", "*.csv")],
                                            initialfile="report.csv")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(self.cols)
            w.writerows(self.shown)
        self.winfo_toplevel().toast(f"Exported {len(self.shown)} rows to {path}")


# ------------------------------------------------------------------ charts (drawn on Canvas)
class StockBars(tk.Canvas):
    """Horizontal stacked bars: stock still in warehouses vs stock already distributed."""

    def __init__(self, parent, height=200):
        super().__init__(parent, bg=CARD, highlightthickness=0, height=height)
        self.data = []
        self.bind("<Configure>", lambda e: self.draw())

    def set(self, data):
        self.data = data
        self.draw()

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 80:
            return
        lx = max(w - 200, 150)
        for x, color, label in ((lx, ACCENT, "In stock"), (lx + 80, GREEN, "Distributed")):
            self.create_rectangle(x, 6, x + 10, 16, fill=color, outline="")
            self.create_text(x + 15, 11, text=label, anchor="w", font=(FONT, 9), fill=MUTED)
        if not self.data:
            self.create_text(w / 2, h / 2, text="No stock data yet", fill=MUTED, font=(FONT, 10))
            return
        top, label_w, right_pad = 32, 120, 120
        row_h = min(36, (h - top - 4) / len(self.data))
        mx = max(a + b for _, a, b in self.data) or 1
        span = max(40, w - label_w - right_pad)
        for i, (name, stock, sent) in enumerate(self.data):
            y = top + i * row_h + row_h / 2
            self.create_text(6, y, text=name, anchor="w", font=(FONT, 10), fill=TEXT)
            self.create_rectangle(label_w, y - 9, label_w + span, y + 9, fill="#f1f5f9", outline="")
            ws, wd = span * stock / mx, span * sent / mx
            if ws > 0:
                self.create_rectangle(label_w, y - 9, label_w + ws, y + 9, fill=ACCENT, outline="")
            if wd > 0:
                self.create_rectangle(label_w + ws, y - 9, label_w + ws + wd, y + 9, fill=GREEN, outline="")
            self.create_text(label_w + span + 10, y, text=f"{stock}  /  {sent}", anchor="w",
                             font=(FONT, 9, "bold"), fill=MUTED)


class Donut(tk.Canvas):
    COLORS = (("FULFILLED", GREEN), ("PARTIAL", "#f59e0b"), ("PENDING", "#94a3b8"))

    def __init__(self, parent, height=200):
        super().__init__(parent, bg=CARD, highlightthickness=0, height=height)
        self.counts = {}
        self.bind("<Configure>", lambda e: self.draw())

    def set(self, counts):
        self.counts = counts
        self.draw()

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 80:
            return
        size = min(h - 16, 170)
        cx, cy, ring = size / 2 + 10, h / 2, 24
        box = (cx - size / 2 + ring / 2, cy - size / 2 + ring / 2, cx + size / 2 - ring / 2, cy + size / 2 - ring / 2)
        total = sum(self.counts.get(k, 0) for k, _ in self.COLORS)
        if total == 0:
            self.create_oval(*box, outline="#e5e7eb", width=ring)
        else:
            start = 90
            for key, color in self.COLORS:
                n = self.counts.get(key, 0)
                if n:
                    extent = -359.9 if n == total else -360.0 * n / total
                    self.create_arc(*box, start=start, extent=extent, style="arc", outline=color, width=ring)
                    start += extent
        self.create_text(cx, cy - 8, text=str(total), font=(FONT, 22, "bold"), fill=HEAD)
        self.create_text(cx, cy + 16, text="requests", font=(FONT, 9), fill=MUTED)
        lx, ly = cx + size / 2 + 26, cy - 34
        for i, (key, color) in enumerate(self.COLORS):
            y = ly + i * 28
            self.create_rectangle(lx, y - 6, lx + 12, y + 6, fill=color, outline="")
            self.create_text(lx + 20, y, text=f"{key.title()}", anchor="w", font=(FONT, 10), fill=TEXT)
            self.create_text(lx + 120, y, text=str(self.counts.get(key, 0)), anchor="w",
                             font=(FONT, 10, "bold"), fill=HEAD)


class Gantt(tk.Canvas):
    """Gantt chart of a scheduling simulation. Block colour = request priority."""

    def __init__(self, parent):
        super().__init__(parent, bg=CARD, highlightthickness=0, height=84)
        self.rows = []
        self.bind("<Configure>", lambda e: self.draw())

    def set(self, rows):
        self.rows = rows
        self.draw()

    def draw(self):
        self.delete("all")
        w = self.winfo_width()
        if w < 80:
            return
        if not self.rows:
            self.create_text(w / 2, 40, text="No pending requests to schedule", fill=MUTED, font=(FONT, 10))
            return
        total = max(r["finish"] for r in self.rows) or 1
        left, right, y0, y1 = 12, 18, 10, 46
        unit = (w - left - right) / total
        for r in self.rows:
            x0, x1 = left + r["start"] * unit, left + r["finish"] * unit
            self.create_rectangle(x0, y0, x1, y1, fill=PRI_COLOR[PRI_NAME[r["priority"]]], outline="white", width=2)
            if x1 - x0 > 30:
                self.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=f"R{r['pid']}", fill="white",
                                 font=(FONT, 9, "bold"))
            self.create_text(x0, y1 + 13, text=str(r["start"]), font=(FONT, 8), fill=MUTED)
        self.create_text(left + total * unit, y1 + 13, text=str(total), font=(FONT, 8), fill=MUTED)
        self.create_line(left, y1 + 3, left + total * unit, y1 + 3, fill=BORDER)


class Monitor(tk.Canvas):
    """Live picture of the worker threads and the loading-dock semaphore."""
    STATES = {"idle": ("#f1f5f9", "#cbd5e1", "Idle"), "alloc": ("#dbeafe", ACCENT, "Allocating"),
              "wait": ("#fef3c7", "#f59e0b", "Waiting for dock"), "load": ("#dcfce7", GREEN, "Loading"),
              "done": ("#f8fafc", "#e2e8f0", "Finished")}

    def __init__(self, parent):
        super().__init__(parent, bg=CARD, highlightthickness=0, height=200)
        self.reset(4, 2)
        self.bind("<Configure>", lambda e: self.draw())

    def reset(self, workers, docks):
        self.names = [f"Worker-{i + 1}" for i in range(workers)]
        self.state = {n: ("idle", None) for n in self.names}
        self.docks = [None] * docks
        self.draw()

    def apply(self, ev):
        kind, name = ev[0], ev[1]
        rid = ev[2] if len(ev) > 2 else None
        if name not in self.state:
            return
        if kind == "start":
            self.state[name] = ("idle", None)
        elif kind == "picked":
            self.state[name] = ("alloc", rid)
        elif kind == "wait_dock":
            self.state[name] = ("wait", rid)
        elif kind == "dock_in":
            self.state[name] = ("load", rid)
            if None in self.docks:
                self.docks[self.docks.index(None)] = (name, rid)
        elif kind == "dock_out":
            self.state[name] = ("idle", None)
            for i, d in enumerate(self.docks):
                if d and d[0] == name:
                    self.docks[i] = None
        elif kind == "finished":
            self.state[name] = ("done", None)
        self.draw()

    def _boxes(self, items, y, h, w, cols):
        gap = 8
        bw = (w - 8 - gap * (cols - 1)) / cols
        for i, item in enumerate(items):
            r, c = divmod(i, cols)
            yield item, 4 + c * (bw + gap), y + r * (h + gap), bw, h

    def draw(self):
        self.delete("all")
        w = self.winfo_width()
        if w < 80:
            return
        self.create_text(4, 10, text="WORKER THREADS", anchor="w", font=(FONT, 8, "bold"), fill=MUTED)
        cols = min(4, len(self.names))
        rows_used = (len(self.names) + cols - 1) // cols
        for name, x, y, bw, bh in self._boxes(self.names, 22, 52, w, cols):
            st, rid = self.state[name]
            fill, edge, label = self.STATES[st]
            self.create_rectangle(x, y, x + bw, y + bh, fill=fill, outline=edge, width=2)
            self.create_text(x + 8, y + 15, text=name, anchor="w", font=(FONT, 9, "bold"), fill=HEAD)
            tail = f" R{rid}" if rid else ""
            self.create_text(x + 8, y + 36, text=label + tail, anchor="w", font=(FONT, 8), fill=TEXT, width=bw - 12)
        y2 = 22 + rows_used * 60 + 8
        free = self.docks.count(None)
        self.create_text(4, y2, text=f"LOADING DOCKS  -  semaphore value: {free} free of {len(self.docks)}",
                         anchor="w", font=(FONT, 8, "bold"), fill=MUTED)
        dcols = min(4, len(self.docks))
        for i, (d, x, y, bw, bh) in enumerate(self._boxes(self.docks, y2 + 12, 40, w, dcols)):
            if d:
                self.create_rectangle(x, y, x + bw, y + bh, fill="#dcfce7", outline=GREEN, width=2)
                self.create_text(x + 8, y + 12, text=f"Dock {i + 1}", anchor="w", font=(FONT, 9, "bold"), fill=HEAD)
                self.create_text(x + 8, y + 28, text=f"{d[0]}  R{d[1]}", anchor="w", font=(FONT, 8), fill=TEXT)
            else:
                self.create_rectangle(x, y, x + bw, y + bh, fill="#f8fafc", outline="#cbd5e1", width=2, dash=(4, 3))
                self.create_text(x + 8, y + 12, text=f"Dock {i + 1}", anchor="w", font=(FONT, 9, "bold"), fill=MUTED)
                self.create_text(x + 8, y + 28, text="free", anchor="w", font=(FONT, 8), fill=MUTED)


# ------------------------------------------------------------------ pages
class Page(tk.Frame):
    title, subtitle = "", ""

    def __init__(self, app):
        super().__init__(app.content, bg=BG)
        self.app = app

    def refresh(self):
        pass


def grid_row(frame, items):
    """Lay widgets out left to right; items = [(widget, weight)]. Weight>0 widgets stretch with the window."""
    for i, (w, weight) in enumerate(items):
        w.grid(row=0, column=i, sticky="new", padx=(0, 0 if i == len(items) - 1 else 12))
        frame.columnconfigure(i, weight=weight)


class TablePage(Page):
    """One or more SQL-backed tables stacked in cards."""

    def __init__(self, app, sections):
        super().__init__(app)
        self.columnconfigure(0, weight=1)
        self.tables = []
        for i, (title, sql, params) in enumerate(sections):
            card = Card(self, title)
            card.grid(row=i, column=0, sticky="nsew", pady=(0, 12) if i < len(sections) - 1 else 0)
            self.rowconfigure(i, weight=1)
            t = Table(card.body, sql, params, height=6)
            t.pack(fill="both", expand=True)
            self.tables.append(t)

    def refresh(self):
        for t in self.tables:
            t.refresh()


PENDING_SQL = ("SELECT * FROM v_pending_requests ORDER BY CASE priority WHEN 'CRITICAL' THEN 1 "
               "WHEN 'HIGH' THEN 2 ELSE 3 END, req_id")
QUEUE_SQL = ("SELECT req_id, area, resource, remaining, priority, status FROM v_pending_requests "
             "ORDER BY CASE priority WHEN 'CRITICAL' THEN 1 WHEN 'HIGH' THEN 2 ELSE 3 END, req_id")
INTEGRITY_SQL = """
SELECT resource, donated, in_stock, distributed,
       CASE WHEN donated = in_stock + distributed THEN 'OK' ELSE 'MISMATCH' END AS balanced
FROM (SELECT r.name AS resource,
        COALESCE((SELECT SUM(quantity) FROM donation     WHERE resource_id=r.resource_id),0) AS donated,
        COALESCE((SELECT SUM(quantity) FROM inventory    WHERE resource_id=r.resource_id),0) AS in_stock,
        COALESCE((SELECT SUM(quantity) FROM distribution WHERE resource_id=r.resource_id),0) AS distributed
      FROM resource r ORDER BY r.name)"""


class DashboardPage(Page):
    def __init__(self, app):
        super().__init__(app)
        self.columnconfigure(0, weight=3, uniform="d")
        self.columnconfigure(1, weight=2, uniform="d")
        self.rowconfigure(2, weight=1)
        strip = tk.Frame(self, bg=BG)
        strip.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        self.cards = {}
        spec = (("Donors", ACCENT), ("Donations", TEAL), ("Areas", PURPLE),
                ("Requests", AMBER), ("Fulfilled", GREEN), ("Open", RED))
        for i, (name, color) in enumerate(spec):
            strip.columnconfigure(i, weight=1, uniform="s")
            c = StatCard(strip, name, color)
            c.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 10, 0))
            self.cards[name] = c

        c1 = Card(self, "Stock overview  (in stock / distributed)")
        c1.grid(row=1, column=0, sticky="nsew", padx=(0, 12), pady=(0, 12))
        self.bars = StockBars(c1.body, height=190)
        self.bars.pack(fill="both", expand=True)

        c2 = Card(self, "Request status")
        c2.grid(row=1, column=1, sticky="nsew", pady=(0, 12))
        self.donut = Donut(c2.body, height=150)
        self.donut.pack(fill="x")
        pills = tk.Frame(c2.body, bg=CARD)
        pills.pack(fill="x", pady=(6, 0))
        self.pills = {}
        for name in ("CRITICAL", "HIGH", "NORMAL"):
            lb = tk.Label(pills, text=f"{name}  0", bg=ROW_TAGS[name][0], fg=ROW_TAGS[name][1],
                          font=(FONT, 9, "bold"), padx=10, pady=5)
            lb.pack(side="left", padx=(0, 6))
            self.pills[name] = lb
        tk.Label(pills, text="open", bg=CARD, fg=MUTED, font=(FONT, 9)).pack(side="left")

        c3 = Card(self, "Integrity check  (donated = in stock + distributed)")
        c3.grid(row=2, column=0, sticky="nsew", padx=(0, 12))
        self.integrity = Table(c3.body, INTEGRITY_SQL, height=4, search=False, export=False)
        self.integrity.pack(fill="both", expand=True)

        c4 = Card(self, "Low-stock alert  (under 100 units)")
        c4.grid(row=2, column=1, sticky="nsew")
        self.low = Table(c4.body, height=4, search=False, export=False)
        self.low.pack(fill="both", expand=True)

    def refresh(self):
        _, rows = query("""SELECT (SELECT COUNT(*) FROM donor), (SELECT COUNT(*) FROM donation),
            (SELECT COUNT(*) FROM affected_area), (SELECT COUNT(*) FROM resource_request),
            (SELECT COUNT(*) FROM resource_request WHERE status='FULFILLED'),
            (SELECT COUNT(*) FROM resource_request WHERE status<>'FULFILLED')""")
        for key, val in zip(self.cards, rows[0]):
            self.cards[key].set(val)
        self.integrity.refresh()
        self.bars.set([(r["resource"], r["in_stock"], r["distributed"]) for r in query(INTEGRITY_SQL)[1]])
        self.donut.set({r[0]: r[1] for r in query("SELECT status, COUNT(*) FROM resource_request GROUP BY status")[1]})
        open_by = {r[0]: r[1] for r in query("SELECT priority, COUNT(*) FROM resource_request "
                                             "WHERE status<>'FULFILLED' GROUP BY priority")[1]}
        for p, name in PRI_NAME.items():
            self.pills[name].config(text=f"{name}  {open_by.get(p, 0)}")
        self.low.show(["resource", "total_stock", "unit"], [tuple(r) for r in inventory.low_stock(100)])


class DonatePage(Page):
    def __init__(self, app, donor_id=None):
        super().__init__(app)
        self.donor_id = donor_id
        self.pickers = []
        if donor_id is not None:
            strip = tk.Frame(self, bg=BG)
            strip.pack(fill="x", pady=(0, 12))
            self.s1, self.s2 = StatCard(strip, "Donations made", TEAL), StatCard(strip, "Total items donated", ACCENT)
            self.s1.pack(side="left", fill="x", expand=True, padx=(0, 10))
            self.s2.pack(side="left", fill="x", expand=True)
        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True)
        form = Card(main, "Make a donation" if donor_id else "Record a donation")
        form.pack(fill="x", pady=(0, 12))
        b = tk.Frame(form.body, bg=CARD)
        b.pack(fill="x")
        items = []
        if donor_id is None:
            self.donor = Picker(b, "Donor", load_donors, width=10)
            self.pickers.append(self.donor)
            items.append((self.donor, 1))
        self.res = Picker(b, "Resource", load_resources, width=10)
        self.wh = Picker(b, "Warehouse", load_warehouses, width=10)
        self.qty = Field(b, "Quantity", width=9)
        self.pickers += [self.res, self.wh]
        btn = tk.Frame(b, bg=CARD)
        tk.Label(btn, text=" ", bg=CARD, font=(FONT, 9)).pack()
        ttk.Button(btn, text="Submit donation", style="Primary.TButton",
                   command=lambda: app.guard(self.submit)).pack()
        grid_row(b, items + [(self.res, 1), (self.wh, 1), (self.qty, 0), (btn, 0)])
        hist = Card(main, "Donation history")
        hist.pack(fill="both", expand=True)
        if donor_id is None:
            sql, params = ("SELECT id, donor, type, resource, quantity, warehouse, substr(date,1,16) AS date "
                          "FROM v_donation_history ORDER BY id DESC"), ()
        else:
            sql = ("SELECT id,resource,quantity,warehouse,substr(date,1,16) AS date FROM v_donation_history "
                   "WHERE donor_id=? ORDER BY id DESC")
            params = (donor_id,)
        self.hist = Table(hist.body, sql, params, height=8)
        self.hist.pack(fill="both", expand=True)

    def submit(self):
        did = self.donor_id if self.donor_id is not None else self.donor.get()
        donation.record_donation(did, self.res.get(), self.wh.get(), to_int(self.qty.get()))
        self.qty.clear()
        self.app.toast("Donation recorded and warehouse stock updated.")
        self.app.refresh_all()

    def refresh(self):
        for p in self.pickers:
            p.reload()
        self.hist.refresh()
        if self.donor_id is not None:
            n, tot = query("SELECT COUNT(*), COALESCE(SUM(quantity),0) FROM donation WHERE donor_id=?",
                           (self.donor_id,))[1][0]
            self.s1.set(n)
            self.s2.set(tot)


class RequestPage(Page):
    def __init__(self, app, area_id=None):
        super().__init__(app)
        self.area_id = area_id
        self.pickers = []
        if area_id is not None:
            strip = tk.Frame(self, bg=BG)
            strip.pack(fill="x", pady=(0, 12))
            self.s1, self.s2 = StatCard(strip, "Open requests", RED), StatCard(strip, "Fulfilled", GREEN)
            self.s1.pack(side="left", fill="x", expand=True, padx=(0, 10))
            self.s2.pack(side="left", fill="x", expand=True)
        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True)
        form = Card(main, "Submit a resource request")
        form.pack(fill="x", pady=(0, 12))
        b = tk.Frame(form.body, bg=CARD)
        b.pack(fill="x")
        items = []
        if area_id is None:
            self.area = Picker(b, "Affected area", load_areas, width=10)
            self.pickers.append(self.area)
            items.append((self.area, 1))
        self.res = Picker(b, "Resource needed", load_resources, width=10)
        self.pickers.append(self.res)
        self.qty = Field(b, "Quantity", width=9)
        self.prio = Segmented(b, "Urgency", [(1, "CRITICAL", "#ef4444"), (2, "HIGH", "#f59e0b"),
                                            (3, "NORMAL", "#3b82f6")], 3)
        btn = tk.Frame(b, bg=CARD)
        tk.Label(btn, text=" ", bg=CARD, font=(FONT, 9)).pack()
        ttk.Button(btn, text="Submit request", style="Primary.TButton",
                   command=lambda: app.guard(self.submit)).pack()
        grid_row(b, items + [(self.res, 1), (self.qty, 0), (self.prio, 0), (btn, 0)])
        hist = Card(main, "Requests and their status")
        hist.pack(fill="both", expand=True)
        label = ("CASE q.priority WHEN 1 THEN 'CRITICAL' WHEN 2 THEN 'HIGH' ELSE 'NORMAL' END AS priority")
        if area_id is None:
            sql = ("SELECT q.request_id AS req_id, a.name AS area, r.name AS resource, "
                   "q.quantity_requested AS requested, q.quantity_fulfilled AS fulfilled, " + label +
                   ", q.status FROM resource_request q JOIN affected_area a ON a.area_id=q.area_id "
                   "JOIN resource r ON r.resource_id=q.resource_id ORDER BY q.request_id DESC")
            params = ()
        else:
            sql = ("SELECT q.request_id AS req_id, r.name AS resource, q.quantity_requested AS requested, "
                   "q.quantity_fulfilled AS fulfilled, " + label + ", q.status, substr(q.created_at,1,16) AS submitted "
                   "FROM resource_request q JOIN resource r ON r.resource_id=q.resource_id "
                   "WHERE q.area_id=? ORDER BY q.request_id DESC")
            params = (area_id,)
        self.hist = Table(hist.body, sql, params, height=8)
        self.hist.pack(fill="both", expand=True)

    def submit(self):
        aid = self.area_id if self.area_id is not None else self.area.get()
        rid = rr.submit_request(aid, self.res.get(), to_int(self.qty.get()), self.prio.get())
        self.qty.clear()
        self.app.toast(f"Request R{rid} submitted ({PRI_NAME[self.prio.get()]}).")
        self.app.refresh_all()

    def refresh(self):
        for p in self.pickers:
            p.reload()
        self.hist.refresh()
        if self.area_id is not None:
            op, ok = query("SELECT SUM(status<>'FULFILLED'), SUM(status='FULFILLED') FROM resource_request "
                           "WHERE area_id=?", (self.area_id,))[1][0]
            self.s1.set(op or 0)
            self.s2.set(ok or 0)


class DispatchPage(Page):
    """Runs the multithreaded priority dispatcher in the background and shows it live."""

    def __init__(self, app):
        super().__init__(app)
        self.msgs = queue.Queue()            # thread-safe channel: worker threads -> GUI thread
        self.running, self.total, self.done = False, 0, 0
        self.columnconfigure(0, weight=11, uniform="c")
        self.columnconfigure(1, weight=9, uniform="c")
        self.rowconfigure(1, weight=2)
        self.rowconfigure(2, weight=3)

        ctl = Card(self, pad=10)
        ctl.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        row = tk.Frame(ctl.body, bg=CARD)
        row.pack(fill="x")

        def spin(label, default, lo, hi):
            tk.Label(row, text=label, bg=CARD, fg=MUTED, font=(FONT, 9)).pack(side="left", padx=(0, 6))
            sp = ttk.Spinbox(row, from_=lo, to=hi, width=3, style="M.TSpinbox")
            sp.set(default)
            sp.pack(side="left", padx=(0, 16))
            return sp
        self.workers = spin("Worker threads", 4, 1, 8)
        self.docks = spin("Docks (semaphore)", 2, 1, 8)
        tk.Label(row, text="Load time", bg=CARD, fg=MUTED, font=(FONT, 9)).pack(side="left", padx=(0, 6))
        self.speed = ttk.Combobox(row, values=["0.2 s", "0.5 s", "0.8 s", "1.5 s"], width=6, state="readonly",
                                  style="M.TCombobox")
        self.speed.set("0.8 s")
        self.speed.pack(side="left", padx=(0, 16))
        self.btn = ttk.Button(row, text="RUN ALLOCATION", style="Success.TButton", command=self.start)
        self.btn.pack(side="left")
        self.status = tk.Label(row, text="Idle", bg=CARD, fg=MUTED, font=(FONT, 10, "bold"))
        self.status.pack(side="right")
        self.progress = ttk.Progressbar(row, length=130, style="Accent.Horizontal.TProgressbar")
        self.progress.pack(side="right", padx=12)

        c1 = Card(self, "Pending queue  (served top to bottom)")
        c1.grid(row=1, column=0, sticky="nsew", padx=(0, 12), pady=(0, 12))
        self.pending = Table(c1.body, QUEUE_SQL, height=4, search=False, export=False)
        self.pending.pack(fill="both", expand=True)
        c2 = Card(self, "Live thread & semaphore monitor")
        c2.grid(row=1, column=1, sticky="nsew", pady=(0, 12))
        self.monitor = Monitor(c2.body)
        self.monitor.pack(fill="both", expand=True)

        c3 = Card(self, "Live thread log")
        c3.grid(row=2, column=0, sticky="nsew", padx=(0, 12))
        logbox = tk.Frame(c3.body, bg="#0b1220")
        logbox.pack(fill="both", expand=True)
        self.log = tk.Text(logbox, height=8, bg="#0b1220", fg="#cbd5e1", insertbackground="white",
                           font=("Consolas", 9), relief="flat", padx=10, pady=8, state="disabled", wrap="word")
        sb = ttk.Scrollbar(logbox, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        for tag, color in (("picked", "#60a5fa"), ("ok", "#4ade80"), ("partial", "#fbbf24"),
                           ("err", "#f87171"), ("head", "#ffffff")):
            self.log.tag_configure(tag, foreground=color)
        self.log.tag_configure("head", font=("Consolas", 9, "bold"))
        c4 = Card(self, "Result")
        c4.grid(row=2, column=1, sticky="nsew")
        self.result = Table(c4.body, height=6, search=False, export=True)
        self.result.pack(fill="both", expand=True)
        self.after(100, self.poll)

    def write(self, text):
        tag = ("err" if "ERROR" in text else "partial" if "PARTIAL" in text else "ok" if "FULFILLED" in text
               else "picked" if "picked" in text else "head" if text.startswith(("Dispatching", "All workers")) else "")
        self.log.config(state="normal")
        self.log.insert("end", text + "\n", tag)
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
            self.app.toast("Workers and docks must be numbers between 1 and 8.", "error")
            return
        self.total = len(rr.pending_requests())
        if not self.total:
            self.app.toast("No pending requests to process. Add some first.", "info")
            return
        work = float(self.speed.get().split()[0])
        self.running, self.done = True, 0
        self.btn.config(state="disabled")
        self.status.config(text="Running...", fg=AMBER)
        self.progress.config(value=0)
        self.monitor.reset(w, d)
        self.result.show(["req", "resource", "needed", "allocated", "status"], [])
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")
        threading.Thread(target=self.controller, args=(w, d, work), daemon=True).start()

    def controller(self, workers, docks, work):
        """Background thread: starts the worker pool, then reports the results to the GUI."""
        try:
            results = allocation.run_dispatch(workers=workers, docks=docks, work_seconds=work,
                                              log=lambda m: self.msgs.put(("log", m)),
                                              on_event=lambda ev: self.msgs.put(("ev", ev)))
            self.msgs.put(("done", results))
        except Exception as e:                       # never leave the button disabled
            self.msgs.put(("log", f"ERROR: {e}"))
            self.msgs.put(("done", []))
        finally:
            db.close_conn()

    def poll(self):
        """Runs in the GUI thread every 80 ms and drains the queue."""
        if not self.winfo_exists():
            return
        try:
            while True:
                kind, payload = self.msgs.get_nowait()
                if kind == "log":
                    self.write(payload)
                elif kind == "ev":
                    self.monitor.apply(payload)
                    if payload[0] == "dock_out":
                        self.done += 1
                        self.progress.config(value=100.0 * self.done / max(1, self.total))
                else:
                    self.result.show(["req", "resource", "needed", "allocated", "status"],
                                     [(f"R{r['request_id']}", r["resource"], r["needed"], r["allocated"], r["status"])
                                      for r in payload])
                    self.running = False
                    self.btn.config(state="normal")
                    self.status.config(text="Finished", fg=GREEN)
                    self.progress.config(value=100)
                    self.app.refresh_all()
                    self.app.toast(f"Allocation finished: {len(payload)} requests processed.")
        except queue.Empty:
            pass
        self.after(80, self.poll)

    def refresh(self):
        self.pending.refresh()


class SchedPage(Page):
    def __init__(self, app):
        super().__init__(app)
        top = Card(self, pad=10)
        top.pack(fill="x", pady=(0, 12))
        row = tk.Frame(top.body, bg=CARD)
        row.pack(fill="x")
        tk.Label(row, text="Each pending request is a process: block width = burst time, colour = priority.\n"
                           "Lower waiting time is better.  Aging boosts requests that wait too long, so none starve.",
                 bg=CARD, fg=MUTED, font=(FONT, 9), justify="left").pack(side="left")
        ttk.Button(row, text="Re-run simulation", style="Primary.TButton", command=self.refresh).pack(side="right")
        for name in ("NORMAL", "HIGH", "CRITICAL"):
            tk.Label(row, text=name, bg=PRI_COLOR[name], fg="white", font=(FONT, 8, "bold"),
                     padx=8, pady=3).pack(side="right", padx=(0, 6))
        self.charts = {}
        for key, title in (("fcfs", "FCFS  (first come, first served)"), ("prio", "Priority scheduling"),
                           ("aging", "Priority + Aging  (every 5 time units)")):
            card = Card(self, title)
            card.pack(fill="x", pady=(0, 12))
            metric = tk.Label(card.head, text="", bg=CARD, fg=MUTED, font=(FONT, 9))
            metric.pack(side="right")
            g = Gantt(card.body)
            g.pack(fill="x")
            self.charts[key] = (g, metric)
        self.insight = tk.Label(self, text="", bg="#dcfce7", fg="#166534", font=(FONT, 10, "bold"),
                                anchor="w", justify="left", padx=16, pady=12, wraplength=900)
        self.insight.pack(fill="x")

    def refresh(self):
        procs = [scheduler.Proc(r["request_id"], r["priority"], i, scheduler.burst_for(r["remaining"]))
                 for i, r in enumerate(rr.pending_requests())]
        stats = {}
        for key, label, policy, aging in (("fcfs", "FCFS", "fcfs", 0), ("prio", "Priority", "priority", 0),
                                          ("aging", "Priority + Aging", "priority", 5)):
            done = scheduler.simulate(procs, policy, aging) if procs else []
            g, metric = self.charts[key]
            g.set(done)
            if done:
                avg = lambda items, k: sum(r[k] for r in items) / len(items) if items else 0.0
                crit = [r for r in done if r["priority"] == 1]
                w, t, c = avg(done, "waiting"), avg(done, "turnaround"), avg(crit, "waiting")
                metric.config(text=f"avg wait {w:.2f}   |   avg turnaround {t:.2f}   |   CRITICAL wait {c:.2f}")
                stats[key] = (w, t, c)
            else:
                metric.config(text="")
        if "fcfs" in stats and stats["fcfs"][2] > 0:
            f, p = stats["fcfs"][2], stats["prio"][2]
            gain = 100.0 * (f - p) / f
            self.insight.config(text=f"Result: priority scheduling cuts the waiting time of CRITICAL requests from "
                                     f"{f:.2f} to {p:.2f} time units ({gain:.0f}% faster than FCFS). "
                                     f"Aging then lets long-waiting NORMAL requests move up, so none starve.")
        else:
            self.insight.config(text="Add requests with different urgency levels to see the difference between the algorithms.")


class ManagePage(Page):
    def __init__(self, app):
        super().__init__(app)
        for i in range(3):
            self.columnconfigure(i, weight=1, uniform="m")
        guard = app.guard

        cols = []
        for i in range(3):
            f = tk.Frame(self, bg=BG)
            f.grid(row=0, column=i, sticky="new", padx=(0 if i == 0 else 6, 0 if i == 2 else 6))
            cols.append(f)

        def card(col, title, row=0, span=1):
            c = Card(cols[col], title)
            c.pack(fill="x", pady=(0, 12))
            return c.body

        b = card(0, "Add warehouse")
        self.w_name, self.w_loc = Field(b, "Warehouse name"), Field(b, "Location")
        self.w_name.pack(fill="x"); self.w_loc.pack(fill="x")
        ttk.Button(b, text="Add warehouse", style="Primary.TButton", command=lambda: guard(self.add_wh)).pack(fill="x")

        b = card(0, "Add resource type", row=1)
        self.r_name, self.r_unit = Field(b, "Resource name"), Field(b, "Unit (e.g. packets)")
        self.r_name.pack(fill="x"); self.r_unit.pack(fill="x")
        ttk.Button(b, text="Add resource", style="Primary.TButton", command=lambda: guard(self.add_res)).pack(fill="x")

        b = card(1, "Register affected area", span=2)
        self.a_name, self.a_dist = Field(b, "Area name"), Field(b, "District")
        self.a_rep, self.a_phone = Field(b, "Representative"), Field(b, "Phone")
        self.a_name.pack(fill="x")
        self.a_dist.pack(fill="x")
        tk.Label(b, text="Disaster type", bg=CARD, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
        self.a_type = ttk.Combobox(b, values=["Flood", "Earthquake", "Cyclone", "Landslide", "Drought", "Other"],
                                   state="readonly", style="M.TCombobox")
        self.a_type.current(0)
        self.a_type.pack(fill="x", pady=(2, 8))
        self.a_rep.pack(fill="x")
        self.a_phone.pack(fill="x")
        ttk.Button(b, text="Register area", style="Primary.TButton", command=lambda: guard(self.add_area)).pack(fill="x")

        b = card(2, "Create user account")
        self.u_name, self.u_pass = Field(b, "Username"), Field(b, "Password", show="*")
        self.u_name.pack(fill="x"); self.u_pass.pack(fill="x")
        tk.Label(b, text="Role", bg=CARD, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
        self.u_role = ttk.Combobox(b, values=["STAFF", "AREA_REP", "DONOR", "ADMIN"], state="readonly",
                                   style="M.TCombobox")
        self.u_role.current(0)
        self.u_role.pack(fill="x", pady=(2, 8))
        self.u_role.bind("<<ComboboxSelected>>", lambda e: self.reload_ref())
        self.u_ref = Picker(b, "Linked to  (only for Donor / Area rep)", self.ref_values)
        self.u_ref.pack(fill="x")
        ttk.Button(b, text="Create user", style="Primary.TButton", command=lambda: guard(self.add_user)).pack(fill="x")

        b = card(2, "Demo data", row=1)
        tk.Label(b, text="Adds 9 sample requests. Food and Medicine demand is higher than stock, "
                         "so priority matters.", bg=CARD, fg=MUTED, font=(FONT, 9), justify="left",
                 wraplength=250).pack(anchor="w", pady=(0, 8))
        ttk.Button(b, text="Load sample requests", style="Success.TButton",
                   command=lambda: guard(self.load_sample)).pack(fill="x")

    def ref_values(self):
        role = self.u_role.get() if hasattr(self, "u_role") else "STAFF"
        return load_areas() if role == "AREA_REP" else load_donors() if role == "DONOR" else []

    def reload_ref(self):
        self.u_ref.var.set("")
        self.u_ref.reload()

    def add_wh(self):
        inventory.add_warehouse(self.w_name.get(), self.w_loc.get())
        self.w_name.clear(); self.w_loc.clear()
        self.done("Warehouse added.")

    def add_res(self):
        inventory.add_resource(self.r_name.get(), self.r_unit.get())
        self.r_name.clear(); self.r_unit.clear()
        self.done("Resource added.")

    def add_area(self):
        rr.add_area(self.a_name.get(), self.a_dist.get(), self.a_type.get(), self.a_rep.get(), self.a_phone.get())
        for f in (self.a_name, self.a_dist, self.a_rep, self.a_phone):
            f.clear()
        self.done("Area registered.")

    def add_user(self):
        role = self.u_role.get()
        ref = cid(self.u_ref.var.get()) if role in ("AREA_REP", "DONOR") else None
        auth.create_user(self.u_name.get(), self.u_pass.get(), role, ref)
        self.u_name.clear(); self.u_pass.clear()
        self.done("User account created.")

    def load_sample(self):
        self.done(f"{seed.sample_requests()} sample requests submitted.")

    def done(self, msg):
        self.app.toast(msg)
        self.app.refresh_all()

    def refresh(self):
        self.u_ref.reload()


# ------------------------------------------------------------------ login screen
class LoginScreen(tk.Frame):
    def __init__(self, app):
        super().__init__(app, bg=CARD)
        self.app = app
        art = tk.Canvas(self, width=500, highlightthickness=0, bg=SIDEBAR)
        art.pack(side="left", fill="y")
        art.bind("<Configure>", lambda e: self.draw_art(art))
        right = tk.Frame(self, bg=CARD)
        right.pack(side="left", fill="both", expand=True)
        form = tk.Frame(right, bg=CARD)
        form.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(form, text="Welcome back", font=(FONT, 24, "bold"), bg=CARD, fg=HEAD).pack(anchor="w")
        tk.Label(form, text="Sign in to the relief management system", font=(FONT, 10), bg=CARD,
                 fg=MUTED).pack(anchor="w", pady=(0, 18))
        self.f_user, self.f_pass = Field(form, "Username", width=34), Field(form, "Password", show="*", width=34)
        self.f_user.pack(fill="x")
        self.f_pass.pack(fill="x")
        self.f_pass.entry.bind("<Return>", lambda e: self.do_login())
        self.f_user.entry.bind("<Return>", lambda e: self.f_pass.entry.focus_set())
        self.show = tk.BooleanVar(value=False)
        tk.Checkbutton(form, text="Show password", variable=self.show, bg=CARD, fg=MUTED, activebackground=CARD,
                       font=(FONT, 9), command=lambda: self.f_pass.entry.config(show="" if self.show.get() else "*"),
                       highlightthickness=0, bd=0).pack(anchor="w")
        self.err = tk.Label(form, text="", bg=CARD, fg=RED, font=(FONT, 9, "bold"))
        self.err.pack(anchor="w", pady=(6, 0))
        ttk.Button(form, text="Login", style="Primary.TButton", command=self.do_login).pack(fill="x", pady=(6, 6))
        ttk.Button(form, text="Register as donor", style="Ghost.TButton", command=self.register_dialog).pack(fill="x")
        tk.Frame(form, bg=BORDER, height=1).pack(fill="x", pady=16)
        tk.Label(form, text="Demo accounts  (click to fill)", bg=CARD, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
        chips = tk.Frame(form, bg=CARD)
        chips.pack(anchor="w", pady=6)
        for label, (u, p) in {"Admin": ("admin", "admin123"), "Staff": ("staff", "staff123"),
                              "Donor": ("donor1", "donor123"), "Area Rep": ("area1", "area123")}.items():
            lb = tk.Label(chips, text=label, bg="#eef2f7", fg=ACCENT, font=(FONT, 9, "bold"), padx=12, pady=6,
                          cursor="hand2")
            lb.pack(side="left", padx=(0, 6))
            lb.bind("<Button-1>", lambda e, u=u, p=p: self.fill(u, p))
        self.after(150, self.f_user.entry.focus_set)

    def fill(self, u, p):
        self.f_user.var.set(u)
        self.f_pass.var.set(p)
        self.err.config(text="")

    def do_login(self):
        user = auth.login(self.f_user.get(), self.f_pass.var.get())
        if not user:
            self.err.config(text="Wrong username or password.")
            return
        self.app.show_main(user)

    def draw_art(self, c):
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        for y in range(0, h, 3):
            c.create_rectangle(0, y, w, y + 3, fill=lerp_color("#0b2239", "#1f5fae", y / max(h, 1)), outline="")
        for r, col in ((380, "#1b4a78"), (300, "#1f5489"), (220, "#255f98")):
            c.create_oval(w - r // 2 - 40, h - r // 2 - 40, w + r // 2 - 40, h + r // 2 - 40, outline=col, width=2)
        c.create_oval(48, 58, 104, 114, fill="white", outline="")
        c.create_rectangle(70, 70, 82, 102, fill=ACCENT, outline="")
        c.create_rectangle(60, 80, 92, 92, fill=ACCENT, outline="")
        c.create_text(48, 160, text="Relief Resource\nManagement System", anchor="nw", fill="white",
                      font=(FONT, 26, "bold"))
        c.create_text(48, 262, text="Collect.  Allocate.  Distribute.", anchor="nw", fill="#9fc1e6", font=(FONT, 13))
        for i, (text, col) in enumerate((("Donation & donor management", "#4ade80"),
                                         ("Inventory & warehouse control", "#60a5fa"),
                                         ("Priority-based request scheduling", "#fbbf24"),
                                         ("Multithreaded allocation & reports", "#f87171"))):
            y = 340 + i * 38
            c.create_oval(50, y + 5, 62, y + 17, fill=col, outline="")
            c.create_text(76, y, text=text, anchor="nw", fill="white", font=(FONT, 11))
        c.create_text(48, h - 40, text="Void Century Coders   |   DBMS + Operating Systems", anchor="w",
                      fill="#7fa3cc", font=(FONT, 9))

    def register_dialog(self):
        win = tk.Toplevel(self.app)
        win.title("Register as donor")
        win.configure(bg=CARD)
        win.resizable(False, False)
        win.transient(self.app)
        body = tk.Frame(win, bg=CARD)
        body.pack(padx=26, pady=20)
        tk.Label(body, text="Create donor account", font=(FONT, 16, "bold"), bg=CARD, fg=HEAD).pack(anchor="w", pady=(0, 10))
        name, phone = Field(body, "Name / organisation"), Field(body, "Phone (must be unique)")
        email, uname, pw = Field(body, "Email (optional)"), Field(body, "Choose a username"), Field(body, "Choose a password", show="*")
        name.pack(fill="x")
        tk.Label(body, text="Donor type", bg=CARD, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
        dtype = ttk.Combobox(body, values=["Individual", "NGO"], state="readonly", style="M.TCombobox")
        dtype.current(0)
        dtype.pack(fill="x", pady=(2, 8))
        for f in (phone, email, uname, pw):
            f.pack(fill="x")
        err = tk.Label(body, text="", bg=CARD, fg=RED, font=(FONT, 9, "bold"))
        err.pack(anchor="w")

        def go():
            try:
                did = donation.register_donor(name.get(), dtype.get(), phone.get(), email.get() or None)
                auth.create_user(uname.get(), pw.var.get(), "DONOR", did)
            except (ValueError, sqlite3.Error) as e:
                err.config(text=str(e))
                return
            win.destroy()
            self.fill(uname.get(), pw.var.get())
            self.app.toast("Registered! Press Login to continue.")
        ttk.Button(body, text="Register", style="Primary.TButton", command=go).pack(fill="x", pady=(8, 0))
        win.update_idletasks()
        x = self.app.winfo_rootx() + (self.app.winfo_width() - win.winfo_width()) // 2
        y = self.app.winfo_rooty() + (self.app.winfo_height() - win.winfo_height()) // 3
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        win.grab_set()


# ------------------------------------------------------------------ main application
class NavItem(tk.Frame):
    def __init__(self, parent, text, command):
        super().__init__(parent, bg=SIDEBAR, cursor="hand2")
        self.bar = tk.Frame(self, bg=SIDEBAR, width=4)
        self.bar.pack(side="left", fill="y")
        self.lbl = tk.Label(self, text=text, bg=SIDEBAR, fg="#c7d6e6", font=(FONT, 10), anchor="w", padx=16, pady=6)
        self.lbl.pack(side="left", fill="x", expand=True)
        self.active = False
        for w in (self, self.lbl, self.bar):
            w.bind("<Button-1>", lambda e: command())
            w.bind("<Enter>", lambda e: self.paint(hover=True))
            w.bind("<Leave>", lambda e: self.paint())

    def paint(self, hover=False):
        bg = SIDE_ACTIVE if self.active else SIDE_HOVER if hover else SIDEBAR
        self.config(bg=bg)
        self.lbl.config(bg=bg, fg="white" if self.active else "#c7d6e6",
                        font=(FONT, 10, "bold" if self.active else "normal"))
        self.bar.config(bg="#60a5fa" if self.active else bg)

    def set_active(self, on):
        self.active = on
        self.paint()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Relief Resource Management System - Void Century Coders")
        w = min(1280, self.winfo_screenwidth() - 40)
        h = min(790, self.winfo_screenheight() - 90)
        self.geometry(f"{w}x{h}+{max(0, (self.winfo_screenwidth() - w) // 2)}+{max(0, (self.winfo_screenheight() - h) // 3)}")
        self.minsize(1050, 640)
        self.configure(bg=BG)
        setup_styles(self)
        db.init_db()
        seed.seed_if_empty()
        self.user, self.pages, self.nav, self.current = None, {}, {}, None
        self._toast = None
        self.show_login()

    # ---- helpers every page can use
    def clear(self):
        for w in self.winfo_children():
            w.destroy()
        self._toast = None

    def toast(self, msg, kind="ok"):
        colors = {"ok": GREEN, "error": RED, "info": ACCENT}
        if self._toast is not None:
            self._toast.destroy()
        t = tk.Label(self, text=msg, bg=colors.get(kind, GREEN), fg="white", font=(FONT, 10, "bold"),
                     padx=18, pady=10)
        t.place(relx=0.5, y=12, anchor="n")
        t.lift()
        self._toast = t
        self.after(3200, lambda: t.destroy() if t.winfo_exists() else None)

    def guard(self, fn):
        """Run an action; show errors as a red toast instead of crashing."""
        try:
            return fn()
        except (ValueError, sqlite3.Error) as e:
            self.toast(str(e), "error")

    # ---- screens
    def show_login(self):
        self.clear()
        self.user, self.pages, self.nav, self.current = None, {}, {}, None
        self.screen = LoginScreen(self)
        self.screen.pack(fill="both", expand=True)

    def show_main(self, user):
        self.clear()
        self.user, self.pages, self.nav, self.current = user, {}, {}, None
        shell = tk.Frame(self, bg=BG)
        shell.pack(fill="both", expand=True)
        side = tk.Frame(shell, bg=SIDEBAR, width=236)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        right = tk.Frame(shell, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        # header
        head = tk.Frame(right, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        head.pack(fill="x")
        left = tk.Frame(head, bg=CARD)
        left.pack(side="left", padx=22, pady=10)
        self.h_title = tk.Label(left, text="", font=(FONT, 17, "bold"), bg=CARD, fg=HEAD)
        self.h_title.pack(anchor="w")
        self.h_sub = tk.Label(left, text="", font=(FONT, 9), bg=CARD, fg=MUTED)
        self.h_sub.pack(anchor="w")
        ttk.Button(head, text="Refresh", style="Ghost.TButton", command=self.refresh_all).pack(side="right", padx=18)
        self.clock = tk.Label(head, text="", font=(FONT, 10), bg=CARD, fg=MUTED)
        self.clock.pack(side="right", padx=6)
        self.content = tk.Frame(right, bg=BG)
        self.content.pack(fill="both", expand=True, padx=18, pady=16)

        # sidebar: logo
        logo = tk.Frame(side, bg=SIDEBAR)
        logo.pack(fill="x", padx=16, pady=(14, 8))
        cv = tk.Canvas(logo, width=38, height=38, bg=SIDEBAR, highlightthickness=0)
        cv.create_oval(1, 1, 37, 37, fill=ACCENT, outline="")
        cv.create_rectangle(16, 8, 22, 30, fill="white", outline="")
        cv.create_rectangle(8, 16, 30, 22, fill="white", outline="")
        cv.pack(side="left")
        lt = tk.Frame(logo, bg=SIDEBAR)
        lt.pack(side="left", padx=10)
        tk.Label(lt, text="Relief Manager", bg=SIDEBAR, fg="white", font=(FONT, 12, "bold")).pack(anchor="w")
        tk.Label(lt, text="Void Century Coders", bg=SIDEBAR, fg="#7fa3cc", font=(FONT, 8)).pack(anchor="w")

        # pages + navigation depend on the role
        role = user["role"]
        inv = [("Stock per warehouse", "SELECT * FROM v_inventory ORDER BY resource, warehouse", ()),
               ("Total stock", "SELECT r.name AS resource, COALESCE(SUM(i.quantity),0) AS total, r.unit "
                               "FROM resource r LEFT JOIN inventory i ON i.resource_id=r.resource_id "
                               "GROUP BY r.resource_id ORDER BY r.name", ())]
        pend = [("Pending requests  (CRITICAL first)", PENDING_SQL, ())]
        dist = [("What went where, when and how much",
                 "SELECT id, req_id, area, resource, quantity, from_warehouse, substr(date,1,16) AS date "
                 "FROM v_distribution_history ORDER BY id DESC", ())]
        P = lambda page, title, sub: (page, title, sub)
        if role == "ADMIN":
            plan = [("OVERVIEW", [("dash", "Dashboard", P(DashboardPage(self), "Dashboard", "Live summary of the whole relief operation"))]),
                    ("RESOURCES", [("inv", "Inventory", P(TablePage(self, inv), "Inventory", "Stock held in every warehouse")),
                                   ("don", "Donations", P(DonatePage(self), "Donations", "Record incoming donations and view history"))]),
                    ("REQUESTS", [("pend", "Pending requirements", P(TablePage(self, pend), "Pending requirements", "Requests waiting for stock, most urgent first")),
                                  ("req", "Requests", P(RequestPage(self), "Requests", "Submit and track resource requests"))]),
                    ("OPERATIONS", [("run", "Run allocation", P(DispatchPage(self), "Run allocation", "Multithreaded priority dispatch with live monitor")),
                                    ("sched", "Scheduling", P(SchedPage(self), "Scheduling simulation", "FCFS vs Priority vs Aging on the current requests")),
                                    ("dist", "Distribution history", P(TablePage(self, dist), "Distribution history", "Every dispatch that has left a warehouse"))]),
                    ("ADMINISTRATION", [("manage", "Manage", P(ManagePage(self), "Manage", "Warehouses, resources, areas, users and demo data"))])]
        elif role == "STAFF":
            plan = [("OVERVIEW", [("dash", "Dashboard", P(DashboardPage(self), "Dashboard", "Live summary of the whole relief operation"))]),
                    ("RESOURCES", [("inv", "Inventory", P(TablePage(self, inv), "Inventory", "Stock held in every warehouse")),
                                   ("don", "Receive donation", P(DonatePage(self), "Receive donation", "Record a donation arriving at a warehouse"))]),
                    ("REQUESTS", [("pend", "Pending requirements", P(TablePage(self, pend), "Pending requirements", "Requests waiting for stock, most urgent first"))]),
                    ("OPERATIONS", [("run", "Run allocation", P(DispatchPage(self), "Run allocation", "Multithreaded priority dispatch with live monitor")),
                                    ("dist", "Distribution history", P(TablePage(self, dist), "Distribution history", "Every dispatch that has left a warehouse"))])]
        elif role == "DONOR":
            plan = [("MY ACCOUNT", [("don", "Donate", P(DonatePage(self, donor_id=user["ref_id"]), "Donate", "Make a donation and see your history"))])]
        else:
            plan = [("MY ACCOUNT", [("req", "My requests", P(RequestPage(self, area_id=user["ref_id"]), "My requests", "Ask for resources and track their status"))])]

        for section, items in plan:
            tk.Label(side, text=section, bg=SIDEBAR, fg="#6f93b8", font=(FONT, 8, "bold"),
                     anchor="w").pack(fill="x", padx=18, pady=(8, 1))
            for key, label, (page, title, sub) in items:
                page.title, page.subtitle = title, sub
                self.pages[key] = page
                item = NavItem(side, label, lambda k=key: self.show_page(k))
                item.pack(fill="x")
                self.nav[key] = item

        # sidebar: user card + logout
        bottom = tk.Frame(side, bg=SIDEBAR)
        bottom.pack(side="bottom", fill="x", padx=16, pady=12)
        ttk.Button(bottom, text="Logout", style="Danger.TButton", command=self.show_login).pack(fill="x", pady=(10, 0))
        uc = tk.Frame(bottom, bg="#14344f")
        uc.pack(fill="x")
        av = tk.Canvas(uc, width=36, height=36, bg="#14344f", highlightthickness=0)
        av.create_oval(2, 2, 34, 34, fill=TEAL, outline="")
        av.create_text(18, 18, text=user["username"][:1].upper(), fill="white", font=(FONT, 12, "bold"))
        av.pack(side="left", padx=8, pady=8)
        tx = tk.Frame(uc, bg="#14344f")
        tx.pack(side="left")
        tk.Label(tx, text=user["username"], bg="#14344f", fg="white", font=(FONT, 10, "bold")).pack(anchor="w")
        tk.Label(tx, text=role.replace("_", " ").title(), bg="#14344f", fg="#9fc1e6", font=(FONT, 8)).pack(anchor="w")

        self.tick()
        self.show_page(next(iter(self.pages)))

    def tick(self):
        if not self.winfo_exists() or not hasattr(self, "clock") or not self.clock.winfo_exists():
            return
        self.clock.config(text=datetime.now().strftime("%a, %d %b %Y   %H:%M:%S"))
        self.after(1000, self.tick)

    def show_page(self, key):
        if self.current:
            self.pages[self.current].pack_forget()
        self.current = key
        page = self.pages[key]
        page.pack(fill="both", expand=True)
        page.refresh()
        self.h_title.config(text=page.title)
        self.h_sub.config(text=page.subtitle)
        for k, item in self.nav.items():
            item.set_active(k == key)

    def refresh_all(self):
        for p in self.pages.values():
            p.refresh()


if __name__ == "__main__":
    App().mainloop()
