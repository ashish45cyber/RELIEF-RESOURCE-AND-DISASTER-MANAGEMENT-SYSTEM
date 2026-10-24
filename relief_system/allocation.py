"""MODULE 4: Allocation & Distribution  (+ the live multithreaded priority dispatcher).

OS concepts used here:
  * Priority scheduling : queue.PriorityQueue orders requests by (priority, arrival).
  * Multithreading      : several worker threads pull requests from that queue concurrently.
  * Mutex               : per-resource lock => stock of one resource changes one-at-a-time.
  * Counting semaphore  : only N loading docks are available; extra workers wait for a free dock.
  * Deadlock avoidance  : a worker never waits for a second lock while holding the first,
                          and dequeue+lock happens inside one small critical section.
"""
import queue
import threading
import time

import db
import inventory
from resource_request import PRIORITY_LABELS, pending_requests


def _allocate_locked(request_id):
    """Allocate stock to one request. Caller MUST already hold the resource mutex.
    Whole thing is ONE transaction: stock decrease + distribution rows + request status."""
    with db.transaction() as c:
        req = c.execute("""SELECT q.resource_id, r.name AS resource, q.quantity_requested,
                                  q.quantity_fulfilled
                           FROM resource_request q JOIN resource r ON r.resource_id = q.resource_id
                           WHERE q.request_id=?""", (request_id,)).fetchone()
        need = req["quantity_requested"] - req["quantity_fulfilled"]
        given = 0
        if need > 0:
            stocks = c.execute("""SELECT warehouse_id, quantity FROM inventory
                                  WHERE resource_id=? AND quantity>0 ORDER BY quantity DESC""",
                               (req["resource_id"],)).fetchall()
            for s in stocks:                       # take from the fullest warehouse first
                take = min(need - given, s["quantity"])
                c.execute("UPDATE inventory SET quantity = quantity - ? "
                          "WHERE warehouse_id=? AND resource_id=?",
                          (take, s["warehouse_id"], req["resource_id"]))
                c.execute("INSERT INTO distribution(request_id,warehouse_id,resource_id,quantity) "
                          "VALUES (?,?,?,?)", (request_id, s["warehouse_id"], req["resource_id"], take))
                given += take
                if given == need:
                    break
        total = req["quantity_fulfilled"] + given
        status = ("FULFILLED" if total == req["quantity_requested"]
                  else "PARTIAL" if total > 0 else "PENDING")
        c.execute("UPDATE resource_request SET quantity_fulfilled=?, status=? WHERE request_id=?",
                  (total, status, request_id))
    return {"request_id": request_id, "resource": req["resource"], "needed": need,
            "allocated": given, "status": status}


def allocate_request(request_id):
    """Single-request allocation (acquires the mutex itself)."""
    res_id = db.get_conn().execute("SELECT resource_id FROM resource_request WHERE request_id=?",
                                   (request_id,)).fetchone()["resource_id"]
    with inventory.get_lock(res_id):
        return _allocate_locked(request_id)


def run_dispatch(workers=4, docks=2, work_seconds=0.3, log=print):
    """Process every pending request using a pool of worker threads."""
    rows = pending_requests()
    if not rows:
        log("No pending requests to process.")
        return []

    pq = queue.PriorityQueue()                     # lowest number = served first
    for r in rows:
        pq.put((r["priority"], r["request_id"], r["resource_id"]))   # request_id breaks ties (FCFS)

    dequeue_lock = threading.Lock()   # makes "take from queue + take resource mutex" one step,
                                      # so mutexes are granted in priority order
    docks_sem = threading.Semaphore(docks)         # counting semaphore: loading bays
    out_lock = threading.Lock()                    # keeps printed lines from mixing together
    results = []

    def say(msg):
        with out_lock:
            log(msg)

    def worker(name):
        try:
            while True:
                with dequeue_lock:
                    try:
                        prio, rid, res_id = pq.get_nowait()
                    except queue.Empty:
                        return
                    mutex = inventory.get_lock(res_id)
                    mutex.acquire()
                    say(f"[{name}] picked  R{rid} ({PRIORITY_LABELS[prio]})")
                try:
                    res = _allocate_locked(rid)
                except Exception as e:             # one bad request must not kill the worker
                    res = {"request_id": rid, "resource": "?", "needed": 0, "allocated": 0,
                           "status": f"ERROR: {e}"}
                finally:
                    mutex.release()
                with docks_sem:                    # wait for a free loading dock
                    say(f"[{name}] loading R{rid}: {res['allocated']}/{res['needed']} "
                        f"{res['resource']} -> {res['status']}")
                    time.sleep(work_seconds)       # simulated packing/loading time
                with out_lock:
                    results.append(res)
        finally:
            db.close_conn()

    log(f"Dispatching {len(rows)} request(s) with {workers} worker threads, {docks} loading docks...\n")
    threads = [threading.Thread(target=worker, args=(f"Worker-{i + 1}",)) for i in range(workers)]
    start = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    log(f"\nAll workers finished in {time.time() - start:.2f}s.")
    return sorted(results, key=lambda r: r["request_id"])
