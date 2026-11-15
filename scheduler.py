"""MODULE 3 (OS part): CPU-scheduling simulation.
Each relief request is treated as a PROCESS:
    arrival = order of submission, burst = time needed to process it, priority = urgency.
Compares FCFS with non-preemptive Priority scheduling (with optional AGING to avoid starvation).
"""
import math
from collections import namedtuple

Proc = namedtuple("Proc", "pid priority arrival burst")


def burst_for(qty):
    """Bigger requests take longer to pack/process: 1 time unit per 50 items (min 1)."""
    return max(1, math.ceil(qty / 50))


def _effective_priority(p, now, aging_interval):
    # Aging: every `aging_interval` units spent waiting improves priority by 1 (min 1).
    if aging_interval <= 0:
        return p.priority
    return max(1, p.priority - (now - p.arrival) // aging_interval)


def simulate(procs, policy="priority", aging_interval=0):
    pending = sorted(procs, key=lambda p: (p.arrival, p.pid))
    t, done = 0, []
    while pending:
        ready = [p for p in pending if p.arrival <= t]
        if not ready:                       # CPU idle until next arrival
            t = min(p.arrival for p in pending)
            continue
        if policy == "fcfs":
            nxt = min(ready, key=lambda p: (p.arrival, p.pid))
        else:
            nxt = min(ready, key=lambda p: (_effective_priority(p, t, aging_interval), p.arrival, p.pid))
        pending.remove(nxt)
        start, t = t, t + nxt.burst
        done.append({"pid": nxt.pid, "priority": nxt.priority, "arrival": nxt.arrival,
                     "burst": nxt.burst, "start": start, "finish": t,
                     "waiting": start - nxt.arrival, "turnaround": t - nxt.arrival})
    return done


def gantt(done):
    bars, times = "|", "0"
    for r in done:
        label = f"R{r['pid']}"
        width = max(len(label) + 2, r["burst"] * 2)
        bars += label.center(width) + "|"
        times += str(r["finish"]).rjust(width + 1)
    return bars + "\n" + times


def _avg(rows, key):
    return sum(r[key] for r in rows) / len(rows) if rows else 0.0


def report(procs, aging_interval=5):
    """Print Gantt charts + waiting times for FCFS, Priority and Priority+Aging."""
    if not procs:
        print("No requests to schedule.")
        return
    print("\nProcess table (request = process):")
    print(f"  {'Req':<5}{'Priority':<10}{'Arrival':<9}{'Burst':<6}")
    for p in sorted(procs, key=lambda p: p.pid):
        print(f"  R{p.pid:<4}{p.priority:<10}{p.arrival:<9}{p.burst:<6}")
    runs = [("FCFS", "fcfs", 0), ("PRIORITY", "priority", 0),
            (f"PRIORITY + AGING (every {aging_interval} units)", "priority", aging_interval)]
    summary = []
    for title, policy, aging in runs:
        done = simulate(procs, policy, aging)
        print(f"\n--- {title} ---")
        print(gantt(done))
        crit = [r for r in done if r["priority"] == 1]
        summary.append((title, _avg(done, "waiting"), _avg(done, "turnaround"), _avg(crit, "waiting")))
    print("\nComparison (lower is better):")
    print(f"  {'Algorithm':<44}{'Avg wait':>9}{'Avg TAT':>9}{'CRITICAL wait':>15}")
    for title, w, t, c in summary:
        print(f"  {title:<44}{w:>9.2f}{t:>9.2f}{c:>15.2f}")
    print("\nNote: priority scheduling serves CRITICAL requests much earlier; aging stops "
          "low-priority requests from starving.")
