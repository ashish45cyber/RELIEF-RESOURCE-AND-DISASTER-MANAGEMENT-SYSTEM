# Relief Resource Collection and Distribution Management System
**Team: Void Century Coders** | Subjects: DBMS + Operating Systems

A centralized system for disaster-relief operations (floods, earthquakes, cyclones...). Donors give
resources, warehouses hold them, affected areas request them, and the system allocates stock
**by urgency, concurrently, and without ever corrupting inventory**.

## How to run (Python 3.8+, no installs needed - sqlite3 and threading are built in)
```
python gui.py      # GUI version (Tkinter window)  <- recommended for the presentation
python main.py     # same system as a terminal menu app
python demo.py     # automatic demo of every DBMS + OS concept (uses a temp database)
```
(On Windows use `py main.py` if `python` is not recognised.)

Sample logins (created on first run): `admin/admin123`, `staff/staff123`, `donor1/donor123`, `area1/area123`.
Anyone can also self-register as a donor from the start menu.

## Files and the module each one implements
| File | Module / purpose |
|---|---|
| `schema.sql` | All tables, constraints, indexes, views (DBMS) |
| `db.py` | Connection per thread, ACID `transaction()` helper |
| `donation.py` | **Module 1** - Donor registration, donation recording |
| `inventory.py` | **Module 2** - Warehouses, stock, per-resource **mutex** |
| `resource_request.py` + `scheduler.py` | **Module 3** - Requests, FCFS vs Priority vs Aging simulation |
| `allocation.py` | **Module 4** - Allocation + multithreaded priority dispatcher |
| `reports.py` | **Module 4** - Inventory / pending / donation / distribution reports + integrity check |
| `gui.py` | Tkinter front-end: login, role-based tabs, tables, forms, live thread log. Allocation runs in a background thread and talks to the window through a thread-safe `queue.Queue`, so the GUI never freezes |
| `auth.py`, `main.py` | Login (salted PBKDF2 hashes), role menus: Admin, Donor, Staff, Area Rep |
| `seed.py`, `demo.py` | Sample data, automatic demonstration |

## DBMS concepts used
**ER model** (`PK`, `FK`; crow's-foot: `1---<` = one-to-many)
```
 DONOR 1----< DONATION >----1 RESOURCE 1----< INVENTORY >----1 WAREHOUSE
                  |                                              |
                  +------------------ >----1 WAREHOUSE ---------+   (donation stored in a warehouse)

 AFFECTED_AREA 1----< RESOURCE_REQUEST >----1 RESOURCE
                           1
                           |
                           ^
                      DISTRIBUTION >----1 WAREHOUSE      (which warehouse supplied which request)
 APP_USER (login) -> ref_id points to DONOR or AFFECTED_AREA depending on role
```
- **Normalization (3NF):** donor details live only in `donor`; resource names only in `resource`;
  other tables reference them by ID. No repeating data -> no update anomalies.
  `inventory` has composite PK `(warehouse_id, resource_id)`; quantity depends on the whole key.
- **Constraints:** `PRIMARY KEY`, `FOREIGN KEY` (enforced with `PRAGMA foreign_keys=ON`), `UNIQUE` (donor phone ->
  no duplicate donors), `CHECK` (`quantity >= 0` so stock can't go negative, priority in 1..3, valid status).
- **Transactions (ACID):** `db.transaction()` = `BEGIN IMMEDIATE ... COMMIT` / `ROLLBACK` on error.
  Donation = insert row + increase stock (atomic). Allocation = decrease stock + insert distribution rows +
  update request status (atomic).
- **Views:** `v_inventory`, `v_pending_requests`, `v_donation_history`, `v_distribution_history`.
- **SQL used:** JOINs (up to 4 tables), GROUP BY / HAVING, subqueries, aggregate functions, UPSERT
  (`ON CONFLICT DO UPDATE`), CASE, indexes.

## Operating System concepts used
| OS concept | Where | What it does |
|---|---|---|
| **Process** | each `resource_request` | Has arrival order, burst (size), priority |
| **Priority scheduling** | `queue.PriorityQueue` in `allocation.py` | CRITICAL(1) < HIGH(2) < NORMAL(3); ties broken FCFS by request id |
| **Scheduling analysis** | `scheduler.py` | Gantt chart, waiting time, turnaround time: FCFS vs Priority |
| **Aging** | `scheduler.py` | Waiting requests gain priority over time -> prevents **starvation** |
| **Multithreading** | `run_dispatch()` | 4 worker threads process requests concurrently |
| **Mutex** | `inventory.get_lock()` | One lock per resource: only one thread changes that stock at a time |
| **Race condition** | `demo.py` Part 1 | Shows lost updates without mutex, correct result with it |
| **Counting semaphore** | `docks_sem` | Only 2 loading docks; a 3rd worker waits for a free dock |
| **Critical section** | `_allocate_locked()` | Read stock -> decrease -> record, protected by mutex + transaction |
| **Deadlock avoidance** | `run_dispatch()` | A thread never waits for a 2nd lock while holding the 1st; each request touches one resource |
| **Producer-consumer** | donations vs allocations | Donations add stock (producers), workers consume it |

## Suggested 5-minute presentation flow
1. Run `python demo.py` and walk through the 3 parts (race condition -> scheduling -> full system).
2. Run `python gui.py`, login as `area1`, submit a request (tab "My Requests"), logout.
3. Login as `admin` -> Manage tab -> "Load sample requests" -> Pending tab -> Scheduling tab (simulate) ->
   Run Allocation tab (RUN ALLOCATION, watch the live thread log) -> Dashboard (integrity check:
   donated = in stock + distributed). Try changing worker threads / loading docks and run again.
4. Point out: critical requests got stock first, normal requests got partial stock, totals still balance.

## Likely viva questions
**Why a mutex when the database already has transactions?**
Transactions keep the DB consistent, the mutex decides *who enters the critical section in what order*
and prevents threads from acting on stale stock numbers. Both layers together are safest.

**Which scheduling algorithm and why?** Non-preemptive priority scheduling - a disaster request can't be
interrupted halfway while packing. Aging fixes its weakness (starvation).

**Why does the GUI use a queue?** Tkinter must only be touched from the main thread. Worker threads put log
messages into a `queue.Queue` (thread-safe) and the GUI reads it every 100 ms - no freezing, no race conditions.

**Is it preemptive?** No. Preemptive would stop a running request when a more urgent one arrives.

**What if two threads want the same item?** They queue on that resource's mutex; the one picked first by
the priority queue gets the stock first. Different resources are processed in parallel.

**What does the semaphore do vs the mutex?** Mutex = 1 holder at a time (mutual exclusion on stock).
Semaphore = N holders (2 loading docks shared by 4 workers).

**Why can't stock go negative?** Allocation takes `min(needed, available)` and the table has `CHECK(quantity >= 0)`.

**Partial fulfilment?** If stock is short, the request becomes `PARTIAL`; the next allocation run continues
from what is still remaining when new donations arrive.

**Which normal form?** 3NF - no partial or transitive dependencies.

**Limitations / future work:** SQLite is a single-writer database (a server DB like MySQL/PostgreSQL would scale
better), no GUI/web front-end, priority is set by the requester (could be verified by admin).
