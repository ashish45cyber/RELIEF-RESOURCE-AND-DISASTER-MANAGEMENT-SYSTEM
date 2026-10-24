-- Relief Resource Collection and Distribution Management System
-- Schema is in 3NF. Every table has a primary key; relationships use foreign keys.

CREATE TABLE IF NOT EXISTS donor (
    donor_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    donor_type    TEXT NOT NULL CHECK (donor_type IN ('Individual','NGO')),
    phone         TEXT NOT NULL UNIQUE,            -- UNIQUE => no duplicate donor records
    email         TEXT,
    registered_on TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS resource (
    resource_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    unit        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS warehouse (
    warehouse_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    location     TEXT NOT NULL
);

-- Stock of each resource in each warehouse (composite primary key)
CREATE TABLE IF NOT EXISTS inventory (
    warehouse_id INTEGER NOT NULL REFERENCES warehouse(warehouse_id),
    resource_id  INTEGER NOT NULL REFERENCES resource(resource_id),
    quantity     INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),   -- stock can never go negative
    PRIMARY KEY (warehouse_id, resource_id)
);

CREATE TABLE IF NOT EXISTS donation (
    donation_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    donor_id     INTEGER NOT NULL REFERENCES donor(donor_id),
    resource_id  INTEGER NOT NULL REFERENCES resource(resource_id),
    warehouse_id INTEGER NOT NULL REFERENCES warehouse(warehouse_id),
    quantity     INTEGER NOT NULL CHECK (quantity > 0),
    donated_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS affected_area (
    area_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL UNIQUE,
    district       TEXT NOT NULL,
    disaster_type  TEXT NOT NULL CHECK (disaster_type IN
                   ('Flood','Earthquake','Cyclone','Landslide','Drought','Other')),
    representative TEXT NOT NULL,
    phone          TEXT
);

-- Each request behaves like a "process": it has a priority, arrival order and burst (work)
CREATE TABLE IF NOT EXISTS resource_request (
    request_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    area_id            INTEGER NOT NULL REFERENCES affected_area(area_id),
    resource_id        INTEGER NOT NULL REFERENCES resource(resource_id),
    quantity_requested INTEGER NOT NULL CHECK (quantity_requested > 0),
    quantity_fulfilled INTEGER NOT NULL DEFAULT 0 CHECK (quantity_fulfilled >= 0),
    priority           INTEGER NOT NULL CHECK (priority IN (1,2,3)),  -- 1=CRITICAL 2=HIGH 3=NORMAL
    status             TEXT NOT NULL DEFAULT 'PENDING'
                       CHECK (status IN ('PENDING','PARTIAL','FULFILLED')),
    created_at         TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    CHECK (quantity_fulfilled <= quantity_requested)
);

CREATE TABLE IF NOT EXISTS distribution (
    distribution_id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id      INTEGER NOT NULL REFERENCES resource_request(request_id),
    warehouse_id    INTEGER NOT NULL REFERENCES warehouse(warehouse_id),
    resource_id     INTEGER NOT NULL REFERENCES resource(resource_id),
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    distributed_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS app_user (
    user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('ADMIN','DONOR','STAFF','AREA_REP')),
    ref_id        INTEGER            -- donor_id for DONOR, area_id for AREA_REP
);

CREATE INDEX IF NOT EXISTS idx_request_sched ON resource_request(status, priority, request_id);
CREATE INDEX IF NOT EXISTS idx_donation_donor ON donation(donor_id);
CREATE INDEX IF NOT EXISTS idx_distribution_req ON distribution(request_id);

-- ---------- Views used by the reporting module ----------
CREATE VIEW IF NOT EXISTS v_inventory AS
SELECT w.name AS warehouse, r.name AS resource, i.quantity, r.unit
FROM inventory i
JOIN warehouse w ON w.warehouse_id = i.warehouse_id
JOIN resource  r ON r.resource_id  = i.resource_id;

CREATE VIEW IF NOT EXISTS v_pending_requests AS
SELECT q.request_id AS req_id, a.name AS area, a.disaster_type AS disaster,
       r.name AS resource, q.quantity_requested AS requested,
       q.quantity_fulfilled AS fulfilled,
       q.quantity_requested - q.quantity_fulfilled AS remaining,
       CASE q.priority WHEN 1 THEN 'CRITICAL' WHEN 2 THEN 'HIGH' ELSE 'NORMAL' END AS priority,
       q.status
FROM resource_request q
JOIN affected_area a ON a.area_id = q.area_id
JOIN resource r      ON r.resource_id = q.resource_id
WHERE q.status <> 'FULFILLED';

CREATE VIEW IF NOT EXISTS v_donation_history AS
SELECT d.donation_id AS id, d.donor_id, o.name AS donor, o.donor_type AS type,
       r.name AS resource, d.quantity, w.name AS warehouse, d.donated_at AS date
FROM donation d
JOIN donor o     ON o.donor_id = d.donor_id
JOIN resource r  ON r.resource_id = d.resource_id
JOIN warehouse w ON w.warehouse_id = d.warehouse_id;

CREATE VIEW IF NOT EXISTS v_distribution_history AS
SELECT x.distribution_id AS id, x.request_id AS req_id, a.name AS area,
       r.name AS resource, x.quantity, w.name AS from_warehouse, x.distributed_at AS date
FROM distribution x
JOIN resource_request q ON q.request_id = x.request_id
JOIN affected_area a    ON a.area_id = q.area_id
JOIN resource r         ON r.resource_id = x.resource_id
JOIN warehouse w        ON w.warehouse_id = x.warehouse_id;
