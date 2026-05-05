"""
Canlı simülasyon motoru.

İki paralel dünya (algo + fixed) aynı bin fill-rate'leri ile çalışır,
ancak kamyon sevk stratejileri farklıdır:
  - algo : 3+ CRITICAL_FULL bin birikince en yakın 20 bin'i topla
  - fixed: Pazartesi / Çarşamba / Cuma saat 08:00'de tüm FULL/CRITICAL bin'leri topla

Üç job:
  FillJob    → her simüle saatte bir bin fill_pct'lerini güncelle
  DispatchJob→ algo (2 sim saatte bir kontrol) + fixed (haftanın belirli günleri)
  AnomalyJob → 5-20 sim dakikada bir rastgele anomali üret

Anomaliler hem bellekte (recent_anomalies) hem DB event_log'a yazılır.
"""
from __future__ import annotations

import asyncio
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# ── Sabitler ──────────────────────────────────────────────────────────────────

DEPOT_LAT, DEPOT_LON = 53.3498, -6.2603
CO2_PER_KM   = 0.28
FUEL_PER_KM  = 0.35
TRUCK_SPEED_KMH = 30.0
SERVICE_SIM_MIN = 5          # simüle dakika / durak servis süresi

# Fill hızları: fill_label başına saat başı dolum yüzdesi
FILL_RATES: dict[str, float] = {"A": 12.0, "B": 4.0, "C": 1.2}

FULL_THRESHOLD     = 60.0
CRITICAL_THRESHOLD = 90.0

DISPATCH_COST_TL = 2_000
FUEL_PRICE_TL    = 45

# Job aralıkları (simüle saniye)
FILL_JOB_INTERVAL_S          = 3_600      # her 1 sim saat
DISPATCH_ALGO_INTERVAL_S     = 7_200      # her 2 sim saat
ANOMALY_MIN_INTERVAL_S       = 300        # min 5 sim dakika
ANOMALY_MAX_INTERVAL_S       = 1_200      # max 20 sim dakika

# Algo tetikleyici
ALGO_MIN_CRITICAL = 3
ALGO_MAX_STOPS    = 20

# Fixed rota: weekday → 0=Pzt 2=Çar 4=Cum, saat 08:00
FIXED_DISPATCH_DAYS = {0, 2, 4}
FIXED_DISPATCH_HOUR = 8
FIXED_CHUNK_SIZE    = 20

# Hız seçenekleri (frontend ile aynı) — sim saniye / gerçek saniye
SPEED_OPTIONS: dict[str, int] = {
    "1x":     1,
    "60x":    60,
    "3600x":  3600,
    "86400x": 86400,
}


# ── Veri sınıfları ─────────────────────────────────────────────────────────────

@dataclass
class BinState:
    bin_id: str
    lat: float
    lon: float
    region: str
    fill_label: str    = "C"
    distance_label: int = 2
    fill_pct: float    = 0.0
    status: str        = "EMPTY"
    is_anomaly: bool   = False
    anomaly_end_sim_s: float = 0.0

    def refresh_status(self) -> None:
        """fill_pct'e göre normal durumu güncelle (anomali aktifse dokunma)."""
        if self.is_anomaly:
            return
        if self.fill_pct >= CRITICAL_THRESHOLD:
            self.status = "CRITICAL_FULL"
        elif self.fill_pct >= FULL_THRESHOLD:
            self.status = "FULL"
        else:
            self.status = "EMPTY"

    def empty(self) -> None:
        self.fill_pct   = 0.0
        self.is_anomaly = False
        self.status     = "EMPTY"


@dataclass
class Stop:
    bin_id: str
    lat: float
    lon: float


@dataclass
class TruckRoute:
    truck_id: int
    route_type: str
    stops: list = field(default_factory=list)   # List[Stop]
    current_stop_idx: int = 0
    lat: float  = DEPOT_LAT
    lon: float  = DEPOT_LON
    from_lat: float = DEPOT_LAT
    from_lon: float = DEPOT_LON
    to_lat: float   = DEPOT_LAT
    to_lon: float   = DEPOT_LON
    leg_start_sim_s: float = 0.0
    leg_end_sim_s: float   = 0.0
    service_end_sim_s: float = 0.0
    status: str     = "en_route"
    at_bin: str | None = None
    to_bin: str | None = None
    progress: float = 0.0


# ── Yardımcı fonksiyonlar ──────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(max(0.0, a)))


def _nearest_neighbor(bins: list[BinState]) -> list[BinState]:
    if not bins:
        return []
    remaining = list(bins)
    result: list[BinState] = []
    cur_lat, cur_lon = DEPOT_LAT, DEPOT_LON
    while remaining:
        closest = min(remaining, key=lambda b: _haversine_km(cur_lat, cur_lon, b.lat, b.lon))
        result.append(closest)
        remaining.remove(closest)
        cur_lat, cur_lon = closest.lat, closest.lon
    return result


def _route_km(ordered: list[BinState]) -> float:
    prev_lat, prev_lon = DEPOT_LAT, DEPOT_LON
    total = 0.0
    for b in ordered:
        total += _haversine_km(prev_lat, prev_lon, b.lat, b.lon)
        prev_lat, prev_lon = b.lat, b.lon
    total += _haversine_km(prev_lat, prev_lon, DEPOT_LAT, DEPOT_LON)
    return total


def _bin_to_dict(b: BinState) -> dict:
    return {
        "bin_id":         b.bin_id,
        "lat":            b.lat,
        "lon":            b.lon,
        "region":         b.region,
        "fill_pct":       round(b.fill_pct, 1),
        "status":         b.status,
        "fill_label":     b.fill_label,
        "distance_label": b.distance_label,
    }


def _truck_to_dict(t: TruckRoute) -> dict:
    return {
        "truck_id":        t.truck_id,
        "route_type":      t.route_type,
        "status":          t.status,
        "lat":             round(t.lat, 6),
        "lon":             round(t.lon, 6),
        "at_bin":          t.at_bin,
        "to_bin":          t.to_bin,
        "progress":        round(t.progress, 3),
        "stops_total":     len(t.stops),
        "current_stop_idx": t.current_stop_idx,
    }


# ── SimulationEngine ───────────────────────────────────────────────────────────

class SimulationEngine:
    """Singleton. main.py içinde başlatılır, router tarafından kullanılır."""

    def __init__(self) -> None:
        self.is_running = False
        self.speed_multiplier: int = 3600   # varsayılan: 1 gerçek sn = 1 sim saat

        self._sim_epoch  = datetime(2024, 1, 1, tzinfo=timezone.utc)
        self._sim_s: float = 0.0            # epoch'tan itibaren geçen simüle saniye

        self.algo_bins:  dict[str, BinState] = {}
        self.fixed_bins: dict[str, BinState] = {}

        self.algo_trucks:  list[TruckRoute] = []
        self.fixed_trucks: list[TruckRoute] = []

        self.algo_kpis  = self._zero_kpis()
        self.fixed_kpis = self._zero_kpis()

        self.recent_anomalies: list[dict] = []

        self._last_fill_s: float            = -FILL_JOB_INTERVAL_S
        self._last_dispatch_algo_s: float   = -DISPATCH_ALGO_INTERVAL_S
        self._last_fixed_day_key: tuple | None = None
        self._next_anomaly_s: float         = self._rand_anomaly_s()

        self._truck_ctr: int  = 0
        self._task: asyncio.Task | None = None

    # ── Genel ──────────────────────────────────────────────────────────────

    @staticmethod
    def _zero_kpis() -> dict:
        return {
            "distance_km":     0.0,
            "fuel_l":          0.0,
            "co2_kg":          0.0,
            "cost_tl":         0.0,
            "dispatch_count":  0,
            "overflow_events": 0,
        }

    @staticmethod
    def _rand_anomaly_s() -> float:
        return random.uniform(ANOMALY_MIN_INTERVAL_S, ANOMALY_MAX_INTERVAL_S)

    @property
    def virtual_clock(self) -> datetime:
        return self._sim_epoch + timedelta(seconds=self._sim_s)

    # ── Veri yükleme ───────────────────────────────────────────────────────

    def load_bins(self, bin_rows: list[dict]) -> None:
        """DB'den gelen satırları her iki dünyaya da yükle."""
        self.algo_bins.clear()
        self.fixed_bins.clear()
        for row in bin_rows:
            bid = row["bin_id"]
            common = dict(
                bin_id         = bid,
                lat            = float(row["lat"]),
                lon            = float(row["lon"]),
                region         = row.get("region") or "Unknown",
                fill_label     = row.get("fill_label") or "C",
                distance_label = int(row.get("distance_label") or 2),
            )
            self.algo_bins[bid]  = BinState(**common)
            self.fixed_bins[bid] = BinState(**common)

    # ── Kontrol ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self.is_running:
            return
        self.is_running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def reset(self) -> None:
        for b in list(self.algo_bins.values()) + list(self.fixed_bins.values()):
            b.fill_pct         = 0.0
            b.status           = "EMPTY"
            b.is_anomaly       = False
            b.anomaly_end_sim_s = 0.0

        self.algo_trucks.clear()
        self.fixed_trucks.clear()
        self.algo_kpis  = self._zero_kpis()
        self.fixed_kpis = self._zero_kpis()
        self.recent_anomalies.clear()

        self._sim_s               = 0.0
        self._last_fill_s         = -FILL_JOB_INTERVAL_S
        self._last_dispatch_algo_s = -DISPATCH_ALGO_INTERVAL_S
        self._last_fixed_day_key  = None
        self._next_anomaly_s      = self._rand_anomaly_s()
        self._truck_ctr           = 0

    # ── Ana döngü ─────────────────────────────────────────────────────────

    TICK_REAL_S = 0.2   # gerçek saniye / tick

    async def _loop(self) -> None:
        while self.is_running:
            self._sim_s += self.TICK_REAL_S * self.speed_multiplier

            self._job_fill()
            self._job_dispatch_algo()
            self._job_dispatch_fixed()
            self._job_anomaly()
            self._heal_anomalies()
            self._advance_trucks()

            await asyncio.sleep(self.TICK_REAL_S)

    # ── FillJob ────────────────────────────────────────────────────────────

    def _job_fill(self) -> None:
        if self._sim_s - self._last_fill_s < FILL_JOB_INTERVAL_S:
            return
        self._last_fill_s = self._sim_s

        for world in (self.algo_bins, self.fixed_bins):
            for b in world.values():
                if b.is_anomaly:
                    continue
                b.fill_pct = min(100.0, b.fill_pct + FILL_RATES[b.fill_label])
                b.refresh_status()

    # ── DispatchJob (Algo) ─────────────────────────────────────────────────

    def _job_dispatch_algo(self) -> None:
        if self._sim_s - self._last_dispatch_algo_s < DISPATCH_ALGO_INTERVAL_S:
            return
        self._last_dispatch_algo_s = self._sim_s

        critical = [
            b for b in self.algo_bins.values()
            if b.status == "CRITICAL_FULL"
        ]
        if len(critical) < ALGO_MIN_CRITICAL:
            return

        # Uzak ve dolu önce
        critical.sort(key=lambda b: (-b.distance_label, -b.fill_pct))
        self._dispatch("algo", critical[:ALGO_MAX_STOPS],
                       self.algo_trucks, self.algo_kpis, self.algo_bins)

    # ── DispatchJob (Fixed) ────────────────────────────────────────────────

    def _job_dispatch_fixed(self) -> None:
        vc = self.virtual_clock
        if vc.weekday() not in FIXED_DISPATCH_DAYS:
            return
        if vc.hour < FIXED_DISPATCH_HOUR:
            return
        day_key = (vc.year, vc.month, vc.day)
        if self._last_fixed_day_key == day_key:
            return
        self._last_fixed_day_key = day_key

        to_visit = [
            b for b in self.fixed_bins.values()
            if b.status in ("FULL", "CRITICAL_FULL")
        ]
        if not to_visit:
            return

        to_visit.sort(key=lambda b: (b.distance_label, b.lat))
        for i in range(0, len(to_visit), FIXED_CHUNK_SIZE):
            self._dispatch("fixed", to_visit[i:i + FIXED_CHUNK_SIZE],
                           self.fixed_trucks, self.fixed_kpis, self.fixed_bins)

    # ── Dispatch yardımcısı ────────────────────────────────────────────────

    def _dispatch(
        self,
        route_type: str,
        bins: list[BinState],
        truck_list: list[TruckRoute],
        kpis: dict,
        world_bins: dict[str, BinState],
    ) -> None:
        ordered = _nearest_neighbor(bins)
        if not ordered:
            return

        self._truck_ctr += 1
        truck = TruckRoute(
            truck_id   = self._truck_ctr,
            route_type = route_type,
            stops      = [Stop(b.bin_id, b.lat, b.lon) for b in ordered],
        )

        first = truck.stops[0]
        dist_first = _haversine_km(DEPOT_LAT, DEPOT_LON, first.lat, first.lon)
        travel_first_s = (dist_first / TRUCK_SPEED_KMH) * 3600

        truck.from_lat = DEPOT_LAT
        truck.from_lon = DEPOT_LON
        truck.to_lat   = first.lat
        truck.to_lon   = first.lon
        truck.leg_start_sim_s = self._sim_s
        truck.leg_end_sim_s   = self._sim_s + travel_first_s
        truck.to_bin          = first.bin_id
        truck.status          = "en_route"

        truck_list.append(truck)

        total_km = _route_km(ordered)
        fuel = total_km * FUEL_PER_KM
        co2  = total_km * CO2_PER_KM
        cost = DISPATCH_COST_TL + fuel * FUEL_PRICE_TL

        kpis["distance_km"]    += total_km
        kpis["fuel_l"]         += fuel
        kpis["co2_kg"]         += co2
        kpis["cost_tl"]        += cost
        kpis["dispatch_count"] += 1

    # ── Truck ilerlemesi ───────────────────────────────────────────────────

    def _advance_trucks(self) -> None:
        s = self._sim_s
        for truck_list, world_bins in (
            (self.algo_trucks,  self.algo_bins),
            (self.fixed_trucks, self.fixed_bins),
        ):
            for truck in truck_list:
                if truck.status == "done":
                    continue
                self._step_truck(truck, s, world_bins)
            truck_list[:] = [t for t in truck_list if t.status != "done"]

    def _step_truck(self, t: TruckRoute, s: float, world_bins: dict) -> None:
        if t.status == "en_route":
            if s >= t.leg_end_sim_s:
                # Durağa vardı
                t.lat    = t.to_lat
                t.lon    = t.to_lon
                stop     = t.stops[t.current_stop_idx]
                t.at_bin = stop.bin_id
                t.to_bin = None
                t.status = "servicing"
                t.service_end_sim_s = t.leg_end_sim_s + SERVICE_SIM_MIN * 60
                t.progress = 1.0
                if stop.bin_id in world_bins:
                    world_bins[stop.bin_id].empty()
            else:
                seg = max(1.0, t.leg_end_sim_s - t.leg_start_sim_s)
                t.progress = (s - t.leg_start_sim_s) / seg
                t.progress = max(0.0, min(1.0, t.progress))
                t.lat = t.from_lat + (t.to_lat - t.from_lat) * t.progress
                t.lon = t.from_lon + (t.to_lon - t.from_lon) * t.progress
                t.to_bin = t.stops[t.current_stop_idx].bin_id

        elif t.status == "servicing":
            if s >= t.service_end_sim_s:
                t.current_stop_idx += 1
                t.at_bin = None
                if t.current_stop_idx < len(t.stops):
                    nxt = t.stops[t.current_stop_idx]
                    dist = _haversine_km(t.lat, t.lon, nxt.lat, nxt.lon)
                    travel_s = (dist / TRUCK_SPEED_KMH) * 3600
                    t.from_lat = t.lat
                    t.from_lon = t.lon
                    t.to_lat   = nxt.lat
                    t.to_lon   = nxt.lon
                    t.leg_start_sim_s = s
                    t.leg_end_sim_s   = s + travel_s
                    t.to_bin   = nxt.bin_id
                    t.status   = "en_route"
                    t.progress = 0.0
                else:
                    # Depoya dön
                    dist = _haversine_km(t.lat, t.lon, DEPOT_LAT, DEPOT_LON)
                    travel_s = (dist / TRUCK_SPEED_KMH) * 3600
                    t.from_lat = t.lat
                    t.from_lon = t.lon
                    t.to_lat   = DEPOT_LAT
                    t.to_lon   = DEPOT_LON
                    t.leg_start_sim_s = s
                    t.leg_end_sim_s   = s + travel_s
                    t.to_bin   = None
                    t.status   = "returning"
                    t.progress = 0.0

        elif t.status == "returning":
            if s >= t.leg_end_sim_s:
                t.lat    = DEPOT_LAT
                t.lon    = DEPOT_LON
                t.status = "done"
            else:
                seg = max(1.0, t.leg_end_sim_s - t.leg_start_sim_s)
                t.progress = (s - t.leg_start_sim_s) / seg
                t.progress = max(0.0, min(1.0, t.progress))
                t.lat = t.from_lat + (t.to_lat - t.from_lat) * t.progress
                t.lon = t.from_lon + (t.to_lon - t.from_lon) * t.progress

    # ── AnomalyJob ─────────────────────────────────────────────────────────

    ANOMALY_TYPES = [
        "OVERFLOW_RISK",
        "FILL_ANOMALY",
        "SENSOR_FIXED_VALUE_ERROR",
        "BIN_OFFLINE",
    ]
    OFFLINE_DURATION_S = (5 * 60, 15 * 60)   # 5-15 sim dakika

    def _job_anomaly(self) -> None:
        if self._sim_s < self._next_anomaly_s:
            return
        self._next_anomaly_s = self._sim_s + self._rand_anomaly_s()

        bin_ids = list(self.algo_bins.keys())
        if not bin_ids:
            return

        bin_id      = random.choice(bin_ids)
        atype       = random.choice(self.ANOMALY_TYPES)
        algo_bin    = self.algo_bins.get(bin_id)
        fixed_bin   = self.fixed_bins.get(bin_id)

        if atype == "OVERFLOW_RISK":
            for b in (algo_bin, fixed_bin):
                if b:
                    b.fill_pct = 95.0
                    b.status   = "CRITICAL_FULL"
            self.algo_kpis["overflow_events"]  += 1
            self.fixed_kpis["overflow_events"] += 1

        elif atype == "FILL_ANOMALY":
            for b in (algo_bin, fixed_bin):
                if b:
                    b.fill_pct = 0.0
                    b.refresh_status()

        elif atype == "SENSOR_FIXED_VALUE_ERROR":
            end_s = self._sim_s + random.uniform(*self.OFFLINE_DURATION_S)
            for b in (algo_bin, fixed_bin):
                if b:
                    b.status           = "SENSOR_ERROR"
                    b.is_anomaly       = True
                    b.anomaly_end_sim_s = end_s

        elif atype == "BIN_OFFLINE":
            end_s = self._sim_s + random.uniform(*self.OFFLINE_DURATION_S)
            for b in (algo_bin, fixed_bin):
                if b:
                    b.status           = "OFFLINE"
                    b.is_anomaly       = True
                    b.anomaly_end_sim_s = end_s

        event = {
            "bin_id":       bin_id,
            "event_type":   atype,
            "virtual_time": self.virtual_clock.isoformat(),
            "details":      f"{atype} @ {bin_id}",
        }
        self.recent_anomalies.append(event)
        if len(self.recent_anomalies) > 50:
            self.recent_anomalies.pop(0)

        # DB'ye yaz (ayrı session)
        self._log_anomaly_db(bin_id, atype, {"virtual_time": self.virtual_clock.isoformat()})

    def _heal_anomalies(self) -> None:
        for world in (self.algo_bins, self.fixed_bins):
            for b in world.values():
                if b.is_anomaly and self._sim_s >= b.anomaly_end_sim_s > 0:
                    b.is_anomaly = False
                    b.refresh_status()

    @staticmethod
    def _log_anomaly_db(bin_id: str, event_type: str, details: dict) -> None:
        try:
            from .database import SessionLocal
            from .schemas import AnomalyType
            from .services.anomaly_service import log_anomaly_event

            db = SessionLocal()
            try:
                log_anomaly_event(db, bin_id, AnomalyType(event_type), details)
                db.commit()
            finally:
                db.close()
        except Exception:
            pass  # engine hiçbir zaman çökmesin

    # ── Snapshot'lar (API için) ────────────────────────────────────────────

    def state_snapshot(self) -> dict:
        return {
            "virtual_clock":    self.virtual_clock.isoformat(),
            "is_running":       self.is_running,
            "speed_multiplier": self.speed_multiplier,
            "algo_bins":        [_bin_to_dict(b) for b in self.algo_bins.values()],
            "fixed_bins":       [_bin_to_dict(b) for b in self.fixed_bins.values()],
            "algo_trucks":      [_truck_to_dict(t) for t in self.algo_trucks],
            "fixed_trucks":     [_truck_to_dict(t) for t in self.fixed_trucks],
        }

    def kpis_snapshot(self) -> dict:
        def _rnd(d: dict) -> dict:
            return {k: (round(v, 1) if isinstance(v, float) else v) for k, v in d.items()}

        a = _rnd(self.algo_kpis)
        f = _rnd(self.fixed_kpis)
        return {
            "algo":  a,
            "fixed": f,
            "savings": {
                "co2_kg":        round(f["co2_kg"]    - a["co2_kg"],    1),
                "fuel_l":        round(f["fuel_l"]    - a["fuel_l"],    1),
                "cost_tl":       round(f["cost_tl"]   - a["cost_tl"],   1),
                "overflow_diff": f["overflow_events"] - a["overflow_events"],
            },
        }


# Singleton — router ve main.py bu nesneyi import eder
engine = SimulationEngine()
