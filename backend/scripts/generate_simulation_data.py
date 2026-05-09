#!/usr/bin/env python3
"""
EcoHaul Simulation Dataset Generator
======================================
Generates ~28 months (2024-01-01 → 2026-05-02) of synthetic bin telemetry
and truck dispatch records for the Algorithm vs Fixed-Route simulation.

Outputs
-------
  backend/data/simulation_events.csv     — state-change events (both worlds)
  backend/data/simulation_dispatches.csv — truck dispatch records
  PostgreSQL: creates + populates simulation_data, simulation_dispatches

Usage (run from project root)
------------------------------
  python backend/scripts/generate_simulation_data.py
  python backend/scripts/generate_simulation_data.py --no-db    # CSV only
  python backend/scripts/generate_simulation_data.py --no-csv   # DB only
"""

import json
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB

# ── Project imports ───────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.database import engine  # noqa: E402

# ── Configuration ─────────────────────────────────────────────────────────────

SEED = 42
START = datetime(2024, 1, 1,  tzinfo=timezone.utc)
END   = datetime(2026, 5, 2, 23, 0, tzinfo=timezone.utc)
ONE_HOUR = timedelta(hours=1)

DEPOT_LAT, DEPOT_LON = 53.3498, -6.2603
CO2_PER_KM  = 0.28   # kg / km  (diesel waste truck)
FUEL_PER_KM = 0.35   # L  / km
AVG_SPEED   = 30.0   # km / h   (urban average)
SERVICE_MIN = 3      # minutes spent at each stop

# These three bins will stay OFFLINE throughout the simulation
# (reserved for real sensor attachments)
OFFLINE_BINS = {"WMS0020", "WMS0053", "WMS0110"}

# Fill-rate ranges: hours from EMPTY to CRITICAL_FULL
FILL_HOURS = {
    "commercial":   (10, 16),
    "market_busy":  (10, 16),   # Fri / Sat
    "market_quiet": (48, 80),   # Mon-Thu, Sun
    "residential":  (60, 100),
    "sparse":       (130, 250),
}

# Fixed-route schedule: Mon=0, Wed=2, Fri=4 at 08:00
FIXED_DAYS = {0, 2, 4}
FIXED_HOUR = 8

# Algorithm-route dispatch triggers
ALGO_INTERVAL_H = 2   # hours between dispatch checks
ALGO_MIN_BINS   = 3   # minimum CRITICAL_FULL bins needed to trigger
ALGO_MAX_STOPS  = 25  # maximum stops per dispatch

OVERFLOW_THRESHOLD_H  = 5.0   # hours CRITICAL before OVERFLOW_RISK is logged
OVERFLOW_COOLDOWN_H   = 12.0  # minimum hours between repeated OVERFLOW_RISK for same bin

DATA_DIR = ROOT / "backend" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in km."""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a  = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def nearest_neighbor(depot: tuple, stops: list) -> list:
    """Greedy nearest-neighbour tour from depot.
    stops: [(bin_id, lat, lon), ...]
    """
    remaining = list(stops)
    ordered   = []
    cur       = depot
    while remaining:
        nxt = min(remaining, key=lambda s: haversine(cur[0], cur[1], s[1], s[2]))
        ordered.append(nxt)
        cur = (nxt[1], nxt[2])
        remaining.remove(nxt)
    return ordered


def compute_stop_times(dispatch_time: datetime, ordered_stops: list):
    """Compute arrival / departure datetimes for each stop.
    Returns (stops_with_times, return_time).
    """
    cur_lat, cur_lon = DEPOT_LAT, DEPOT_LON
    cur_ts = dispatch_time
    result = []
    for bin_id, lat, lon in ordered_stops:
        dist_km  = haversine(cur_lat, cur_lon, lat, lon)
        travel_h = dist_km / AVG_SPEED
        arrival  = cur_ts + timedelta(hours=travel_h)
        depart   = arrival + timedelta(minutes=SERVICE_MIN)
        result.append({
            "bin_id":         bin_id,
            "lat":            lat,
            "lon":            lon,
            "arrival_time":   arrival.isoformat(),
            "departure_time": depart.isoformat(),
        })
        cur_lat, cur_lon = lat, lon
        cur_ts = depart
    if result:
        last_d  = datetime.fromisoformat(result[-1]["departure_time"])
        d_back  = haversine(result[-1]["lat"], result[-1]["lon"], DEPOT_LAT, DEPOT_LON)
        return_time = last_d + timedelta(hours=d_back / AVG_SPEED)
    else:
        return_time = dispatch_time
    return result, return_time


def route_kpis(stops_with_times: list):
    """Compute total distance, fuel, CO2 for a dispatch (depot → stops → depot)."""
    pts = (
        [(DEPOT_LAT, DEPOT_LON)]
        + [(s["lat"], s["lon"]) for s in stops_with_times]
        + [(DEPOT_LAT, DEPOT_LON)]
    )
    dist = sum(haversine(pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1])
               for i in range(len(pts) - 1))
    return round(dist, 3), round(dist * FUEL_PER_KM, 3), round(dist * CO2_PER_KM, 3)


def sample_fill_h(profile: str, ts: datetime, rng: random.Random) -> float:
    """Sample a fill-duration (hours) for a bin given its profile and the current weekday."""
    if profile == "market":
        key = "market_busy" if ts.weekday() in (4, 5) else "market_quiet"
    else:
        key = profile
    lo, hi = FILL_HOURS[key]
    return rng.uniform(lo, hi)


def assign_profile(sorted_index: int) -> str:
    """Deterministic profile assignment by sorted bin index."""
    if sorted_index < 60:   return "commercial"
    if sorted_index < 90:   return "market"
    if sorted_index < 210:  return "residential"
    return "sparse"


# ── Core simulation ───────────────────────────────────────────────────────────

def simulate_world(bins_df: pd.DataFrame, world_type: str):
    """
    Simulate one world ('algo' or 'fixed') for the full date range.
    Returns (event_rows, dispatch_rows).
    """
    init_rng = random.Random(SEED)

    # ── Build per-bin state dicts ─────────────────────────────────────────
    bins: dict[str, dict] = {}
    sorted_bins = bins_df.sort_values("bin_id")

    for idx, row in enumerate(sorted_bins.itertuples(index=False)):
        bid = row.bin_id
        if bid in OFFLINE_BINS:
            continue
        profile   = assign_profile(idx)
        fill_h    = sample_fill_h(profile, START, random.Random(hash(bid) & 0x7FFFFFFF))
        # Scatter initial fill progress so not everything triggers at once
        offset    = init_rng.uniform(0, fill_h * 0.95)
        bins[bid] = {
            "profile":    profile,
            "lat":        row.latitude,
            "lon":        row.longitude,
            "region":     row.region,
            "state":      "EMPTY",
            "fill_start": START - timedelta(hours=offset),
            "fill_h":     fill_h,
            "crit_since": None,
            "overflow_at": None,     # last time OVERFLOW_RISK was logged
            "rng":        random.Random(hash(bid) & 0x7FFFFFFF),
        }

    # ── Build zone map (for fixed dispatch) ───────────────────────────────
    # Group bins into ~12 geographic north-south zones by latitude
    N_ZONES = 12
    sorted_by_lat = sorted(bins.keys(), key=lambda bid: bins[bid]["lat"])
    zone_size = max(1, len(sorted_by_lat) // N_ZONES)
    zones: dict[str, list[str]] = {}
    for i, bid in enumerate(sorted_by_lat):
        zone_id = f"ZONE_{i // zone_size:02d}"
        zones.setdefault(zone_id, []).append(bid)

    events:    list[dict] = []
    dispatches: list[dict] = []
    truck_counter = 0

    def evt(bid, ts, old_s, new_s, anomaly=None):
        events.append({
            "bin_id":       bid,
            "timestamp":    ts.isoformat(),
            "old_state":    old_s,
            "new_state":    new_s,
            "anomaly_type": anomaly,
            "route_type":   world_type,
            "source":       "simulated",
        })

    def do_dispatch(ts: datetime, bin_ids: list[str]):
        nonlocal truck_counter
        if not bin_ids:
            return
        stops_raw = [(bid, bins[bid]["lat"], bins[bid]["lon"]) for bid in bin_ids if bid in bins]
        if not stops_raw:
            return
        ordered        = nearest_neighbor((DEPOT_LAT, DEPOT_LON), stops_raw)
        stops_timed, rt = compute_stop_times(ts, ordered)
        dist, fuel, co2 = route_kpis(stops_timed)
        truck_counter += 1
        t_id = (truck_counter % 8) + 1   # 8 trucks in fleet
        dispatches.append({
            "route_type":    world_type,
            "truck_id":      t_id,
            "dispatch_time": ts.isoformat(),
            "return_time":   rt.isoformat(),
            "stops":         json.dumps(stops_timed),
            "distance_km":   dist,
            "fuel_l":        fuel,
            "co2_kg":        co2,
        })
        # Empty collected bins at their respective arrival times
        for stop in stops_timed:
            bid = stop["bin_id"]
            if bid not in bins:
                continue
            arrival = datetime.fromisoformat(stop["arrival_time"])
            evt(bid, arrival, bins[bid]["state"], "EMPTY")
            b = bins[bid]
            b["state"]       = "EMPTY"
            b["fill_start"]  = arrival
            b["fill_h"]      = sample_fill_h(b["profile"], arrival, b["rng"])
            b["crit_since"]  = None
            b["overflow_at"] = None

    # ── Main hourly loop ──────────────────────────────────────────────────
    algo_last_check = START
    current = START
    day_count = (END - START).days + 1
    report_every = 365  # print progress every N days

    while current <= END:
        if current.hour == 0 and (current - START).days % report_every == 0:
            pct = (current - START) / (END - START) * 100
            print(f"    [{world_type}] {current.date()}  ({pct:.0f}%)")

        is_busy_day = current.weekday() in (4, 5)  # Fri / Sat (market days)

        # ── Update every bin ─────────────────────────────────────────────
        for bid, b in list(bins.items()):
            state = b["state"]

            if state == "CRITICAL_FULL":
                if b["crit_since"] is None:
                    b["crit_since"] = current
                hours_crit = (current - b["crit_since"]).total_seconds() / 3600

                # OVERFLOW_RISK: log for fixed world (algorithm reacts before this)
                if (world_type == "fixed"
                        and hours_crit >= OVERFLOW_THRESHOLD_H
                        and (b["overflow_at"] is None
                             or (current - b["overflow_at"]).total_seconds() / 3600
                             >= OVERFLOW_COOLDOWN_H)):
                    evt(bid, current, "CRITICAL_FULL", "CRITICAL_FULL", "OVERFLOW_RISK")
                    b["overflow_at"] = current

                # Occasional FILL_ANOMALY (rapid dump / sensor spike) for commercial/market bins
                if (b["profile"] in ("commercial", "market")
                        and b["rng"].random() < 0.0005   # ~0.05% chance per hour
                        and hours_crit < 1.0):
                    evt(bid, current,                          "CRITICAL_FULL", "EMPTY",         "FILL_ANOMALY")
                    evt(bid, current + timedelta(hours=2),     "EMPTY",         "CRITICAL_FULL", "FILL_ANOMALY")
                    b["crit_since"] = current + timedelta(hours=2)

            elif state in ("EMPTY", "FULL"):
                elapsed_h = (current - b["fill_start"]).total_seconds() / 3600
                fill_h    = b["fill_h"]

                # Market bins: if we cross a busy day boundary, speed up remaining fill
                if b["profile"] == "market" and current.hour == 0:
                    if is_busy_day:
                        # Compress remaining fill time to busy-day rate
                        remaining_frac = max(0, 1 - elapsed_h / fill_h)
                        b["fill_h"] = elapsed_h + b["rng"].uniform(
                            *FILL_HOURS["market_busy"]) * remaining_frac
                    else:
                        remaining_frac = max(0, 1 - elapsed_h / fill_h)
                        b["fill_h"] = elapsed_h + b["rng"].uniform(
                            *FILL_HOURS["market_quiet"]) * remaining_frac

                if state == "EMPTY" and elapsed_h >= fill_h * 0.60:
                    evt(bid, current, "EMPTY", "FULL")
                    b["state"] = "FULL"

                elif state == "FULL" and elapsed_h >= fill_h:
                    evt(bid, current, "FULL", "CRITICAL_FULL")
                    b["state"]      = "CRITICAL_FULL"
                    b["crit_since"] = current

        # ── Dispatch logic ────────────────────────────────────────────────
        if world_type == "algo":
            elapsed_since_check = (current - algo_last_check).total_seconds() / 3600
            if elapsed_since_check >= ALGO_INTERVAL_H:
                algo_last_check = current
                critical = [bid for bid, b in bins.items() if b["state"] == "CRITICAL_FULL"]
                if len(critical) >= ALGO_MIN_BINS:
                    # Sort by how long they've been critical (oldest first)
                    critical.sort(key=lambda bid: bins[bid]["crit_since"] or current)
                    do_dispatch(current, critical[:ALGO_MAX_STOPS])

        else:  # fixed
            if current.weekday() in FIXED_DAYS and current.hour == FIXED_HOUR:
                for zone_bins in zones.values():
                    if zone_bins:
                        do_dispatch(current, zone_bins)

        current += ONE_HOUR

    print(f"    [{world_type}] Done. {len(events):,} events, {len(dispatches):,} dispatches.")
    return events, dispatches


# ── SENSOR_FIXED_VALUE_ERROR injection ───────────────────────────────────────

def inject_sensor_errors(events: list[dict], bins_df: pd.DataFrame):
    """Add SENSOR_FIXED_VALUE_ERROR periods for a few random bins."""
    rng = random.Random(SEED + 99)
    active_bins = [b for b in bins_df["bin_id"].tolist() if b not in OFFLINE_BINS]
    chosen = rng.sample(active_bins, min(4, len(active_bins)))
    for bid in chosen:
        start_err = START + timedelta(days=rng.randint(30, 600))
        for world in ("algo", "fixed"):
            events.append({
                "bin_id":       bid,
                "timestamp":    start_err.isoformat(),
                "old_state":    None,
                "new_state":    "SENSOR_ERROR",
                "anomaly_type": "SENSOR_FIXED_VALUE_ERROR",
                "route_type":   world,
                "source":       "simulated",
            })
    return events


# ── DB migration ──────────────────────────────────────────────────────────────

MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS simulation_data (
    id            BIGSERIAL PRIMARY KEY,
    bin_id        TEXT         NOT NULL,
    timestamp     TIMESTAMPTZ  NOT NULL,
    old_state     TEXT,
    new_state     TEXT         NOT NULL,
    anomaly_type  TEXT,
    route_type    TEXT,
    source        TEXT         NOT NULL DEFAULT 'simulated'
);
CREATE INDEX IF NOT EXISTS idx_simdata_bin_ts
    ON simulation_data (bin_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_simdata_route_ts
    ON simulation_data (route_type, timestamp);

CREATE TABLE IF NOT EXISTS simulation_dispatches (
    id             BIGSERIAL PRIMARY KEY,
    route_type     TEXT         NOT NULL,
    truck_id       INT          NOT NULL,
    dispatch_time  TIMESTAMPTZ  NOT NULL,
    return_time    TIMESTAMPTZ  NOT NULL,
    stops          JSONB        NOT NULL,
    distance_km    FLOAT,
    fuel_l         FLOAT,
    co2_kg         FLOAT
);
CREATE INDEX IF NOT EXISTS idx_simdisp_route_dtime
    ON simulation_dispatches (route_type, dispatch_time);
CREATE INDEX IF NOT EXISTS idx_simdisp_route_rtime
    ON simulation_dispatches (route_type, return_time);
"""


def run_migration():
    print("Running DB migration...")
    with engine.begin() as conn:
        for stmt in MIGRATION_SQL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(text(stmt))
    print("  Tables ready.")


def insert_to_db(events_df: pd.DataFrame, dispatches_df: pd.DataFrame):
    print("Inserting into DB...")
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM simulation_dispatches"))
        conn.execute(text("DELETE FROM simulation_data"))

    # Convert ISO strings to timezone-aware datetimes so psycopg accepts TIMESTAMPTZ
    ev = events_df.copy()
    ev["timestamp"] = pd.to_datetime(ev["timestamp"], format="ISO8601", utc=True)

    chunk = 5_000
    total_events = len(ev)
    for i in range(0, total_events, chunk):
        batch = ev.iloc[i : i + chunk]
        batch.to_sql("simulation_data", engine, if_exists="append", index=False,
                     method="multi")
        if (i // chunk) % 10 == 0:
            print(f"  Events: {min(i + chunk, total_events):,} / {total_events:,}")

    dp = dispatches_df.copy()
    dp["dispatch_time"] = pd.to_datetime(dp["dispatch_time"], format="ISO8601", utc=True)
    dp["return_time"]   = pd.to_datetime(dp["return_time"],   format="ISO8601", utc=True)
    dchunk = 500  # 8 cols × 500 = 4000 params, well under 65535
    total_disp = len(dp)
    for i in range(0, total_disp, dchunk):
        dp.iloc[i : i + dchunk].to_sql(
            "simulation_dispatches", engine,
            if_exists="append", index=False, method="multi",
            dtype={"stops": JSONB},
        )
    print(f"  Dispatches: {total_disp:,} rows inserted.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    no_db  = "--no-db"  in sys.argv
    no_csv = "--no-csv" in sys.argv

    bins_csv = DATA_DIR / "bins_demo_300.csv"
    if not bins_csv.exists():
        bins_csv = DATA_DIR / "bins_wgs84.csv"
    print(f"Loading bins from {bins_csv.name}...")
    bins_df = pd.read_csv(bins_csv)
    # Normalise column names
    bins_df = bins_df.rename(columns={"lat": "latitude", "lon": "longitude"}, errors="ignore")
    print(f"  {len(bins_df)} bins loaded. OFFLINE reserved: {OFFLINE_BINS}")

    # ── Simulate both worlds ──────────────────────────────────────────────
    print("\nSimulating ALGORITHM world...")
    algo_events, algo_dispatches = simulate_world(bins_df, "algo")

    print("\nSimulating FIXED ROUTE world...")
    fixed_events, fixed_dispatches = simulate_world(bins_df, "fixed")

    # ── Combine and inject extra anomalies ────────────────────────────────
    all_events = algo_events + fixed_events
    all_events = inject_sensor_errors(all_events, bins_df)
    all_events.sort(key=lambda e: e["timestamp"])

    all_dispatches = algo_dispatches + fixed_dispatches
    all_dispatches.sort(key=lambda d: d["dispatch_time"])

    events_df    = pd.DataFrame(all_events)
    dispatch_df  = pd.DataFrame(all_dispatches)

    print(f"\nTotal events:    {len(events_df):,}")
    print(f"Total dispatches: {len(dispatch_df):,}")

    # ── CSV output ────────────────────────────────────────────────────────
    if not no_csv:
        ev_path = DATA_DIR / "simulation_events.csv"
        dp_path = DATA_DIR / "simulation_dispatches.csv"
        events_df.to_csv(ev_path, index=False)
        dispatch_df.to_csv(dp_path, index=False)
        print(f"\nCSV written:")
        print(f"  {ev_path}")
        print(f"  {dp_path}")

    # ── DB output ─────────────────────────────────────────────────────────
    if not no_db:
        run_migration()
        insert_to_db(events_df, dispatch_df)

    print("\nDone.")


if __name__ == "__main__":
    main()
