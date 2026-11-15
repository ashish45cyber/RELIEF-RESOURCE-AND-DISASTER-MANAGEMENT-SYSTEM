"""Automatic demonstration of every DBMS + OS concept.   Run:  python demo.py
Uses a temporary database, so your real data (relief.db) is never touched."""
import os
import tempfile
import threading
import time

import allocation
import db
import reports
import resource_request as rr
import scheduler
import seed


def banner(t):
    print("\n" + "=" * 70 + f"\n  {t}\n" + "=" * 70)


def race_demo():
    banner("PART 1: RACE CONDITION  vs  MUTEX  (synchronization)")
    print("10 threads each remove 5 units, 20 times, from a stock of 1000.  Correct answer: 0\n")

    def run(use_lock):
        stock = {"qty": 1000}
        lock = threading.Lock()

        def take():
            for _ in range(20):
                if use_lock:
                    with lock:
                        cur = stock["qty"]; time.sleep(0.0002); stock["qty"] = cur - 5
                else:
                    cur = stock["qty"]; time.sleep(0.0002); stock["qty"] = cur - 5  # read-modify-write RACE

        ts = [threading.Thread(target=take) for _ in range(10)]
        [t.start() for t in ts]; [t.join() for t in ts]
        return stock["qty"]

    print(f"  WITHOUT mutex -> final stock = {run(False):>4}   (WRONG: updates were lost)")
    print(f"  WITH    mutex -> final stock = {run(True):>4}   (correct)")


def scheduling_demo():
    banner("PART 2: PRIORITY SCHEDULING  vs  FCFS  (CPU scheduling)")
    # R2 is a NORMAL request that keeps getting overtaken by a stream of CRITICAL ones
    procs = [scheduler.Proc(1, 3, 0, 3), scheduler.Proc(2, 3, 1, 2), scheduler.Proc(3, 1, 2, 2),
             scheduler.Proc(4, 1, 3, 2), scheduler.Proc(5, 1, 4, 2), scheduler.Proc(6, 1, 5, 2),
             scheduler.Proc(7, 1, 6, 2)]
    scheduler.report(procs, aging_interval=3)


def system_demo():
    banner("PART 3: FULL SYSTEM - multithreaded priority dispatch on the database")
    path = os.path.join(tempfile.mkdtemp(), "demo.db")
    db.use_database(path)
    db.init_db()
    seed.seed_if_empty()
    seed.sample_requests()
    print("Stock is deliberately SMALLER than total demand (Food: 500 in stock, 750 requested).")
    reports.inventory_report()
    reports.pending_report()
    print()
    allocation.run_dispatch(workers=4, docks=2, work_seconds=0.4)
    reports.pending_report()
    reports.distribution_report()
    ok = reports.integrity_check()
    print("\nResult:", "ALL STOCK BALANCED - no lost or duplicated inventory." if ok else "MISMATCH FOUND!")
    db.close_conn()


if __name__ == "__main__":
    race_demo()
    scheduling_demo()
    system_demo()
