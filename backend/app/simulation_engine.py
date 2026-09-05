"""
Canlı simülasyon motoru.

İki paralel dünya:
  - algo : DPET algoritması — ETF + trafik + kapasite bazlı dinamik dispatch
  - fixed: Seçili algoritmaya göre değişen dispatch stratejisi

Depot : en kuzey bin + 0.005° offset (parlak mor işaret)
Rota  : Fixed dünyası için seçilebilir üç algoritma (bkz. FIXED_ROUTE_ALGORITHMS):
          - lo_dcs : STATİK — her gün 06:00'da TÜM bin'leri kapsayan, önceden
                     hesaplanmış program (K-Means + discrete cuckoo search +
                     2-opt, Goswami et al. 2026 — makalenin kendisi de statik).
          - aco    : DİNAMİK — her gün 06:00'da doluluk-farkında "must-go" bin
                     seçimi + K-Means + ant colony optimization (Kim et al. 2023).
          - hho    : DİNAMİK — günde iki kez pre-optimization (09:00/21:00) +
                     periyodik re-optimization (K-Means + improved Harris
                     Hawks optimization, Huang et al. 2026; tek filoya
                     uyarlanmış).
        lo_dcs rotaları startup'ta/algoritma değişiminde bir kez hesaplanır;
        aco/hho'nunki dispatch döngüsünde anlık hesaplanır (bkz. lo_dcs.py,
        aco_route.py, hho_route.py).

Filo         : Her dünya için MAX_FLEET_SIZE = 12 kamyon
Kapasite     : Hacimsel model — %100 bin kamyonun %5'ini doldurur (BIN_VOLUME_FRACTION)
Rota genişletme: Acil bin (%90+) önce mevcut kamyona eklenir, kapasite/sapma uygunsa
Dolum        : Phase 1 environment — saatlik profil × event × gürültü
Taşma        : Her dünya bağımsız sayar; %100 kaldığı her tick overflow+1
"""
from __future__ import annotations

import asyncio
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .aco_route import aco_route
from .dpet import BIN_VOLUME_FRACTION, TRUCK_CAPACITY, Stop, dpet_dispatch
from .environment import (
    DistrictType, Event, EventManager,
    assign_district, effective_fill_rate,
)
from .hho_route import hho_route
from .lo_dcs import lo_dcs_route
from .predictor import FillPredictor
from .route_common import kmeans_clusters

# Fixed dünyası için seçilebilir rota kurucular — hepsi aynı imzayı paylaşır:
# (cluster_bins, depot_lat, depot_lon) -> list[Stop]. Sağ panelin üstündeki
# dropdown'dan seçilir; simülasyon çalışırken değiştirilemez (bkz. router).
FIXED_ROUTE_ALGORITHMS = {
    "lo_dcs": lo_dcs_route,   # Goswami et al. 2026 — discrete cuckoo search + 2-opt
    "aco":    aco_route,      # Kim et al. 2023 — k-means + ant colony optimization
    "hho":    hho_route,      # Huang et al. 2026 — improved Harris Hawks optimization
}
DEFAULT_FIXED_ALGORITHM = "lo_dcs"


# =============================================================================
# region: SABİTLER
# Simülasyon boyunca değişmeyen tüm parametre ve eşik değerleri burada
# tanımlanır. Depot konumu, yakıt/CO2 katsayıları, hız, dolum aralıkları,
# dispatch eşikleri ve tier mantığına ait tüm sayısal değerler bu bölümdedir.
# =============================================================================

_DEFAULT_DEPOT_LAT, _DEFAULT_DEPOT_LON = 53.3498, -6.2603
DEPOT_NORTH_OFFSET = 0.005          # ~550 m kuzey offset

CO2_PER_KM        = 0.28
FUEL_PER_KM       = 0.35            # L/km boş kamyon
WEIGHT_MULTIPLIER = 0.8             # tam dolu kamyon %80 daha fazla yakıt yakar
TRUCK_SPEED_KMH   = 30.0
SERVICE_SIM_MIN   = 5               # sim dakika / durak servis süresi

# Her bin startup'ta kendi label aralığından rastgele bir oran alır (%/sim-saat)
FILL_RATE_RANGES: dict[str, tuple[float, float]] = {
    "A": (12.0, 16.0),  # hızlı: 6–8 sim saatte dolar  → algo ETF avantajı belirgin
    "B": (4.0,  8.0),   # orta : 12–25 sim saatte dolar → orta aciliyet
    "C": (0.5,  1.5),   # yavaş: 67–200 sim saatte dolar → fixed rota boşa sefer yapar
}
FULL_THRESHOLD     = 50.0
CRITICAL_THRESHOLD = 85.0

DISPATCH_COST_TL = 2_000
FUEL_PRICE_TL    = 45

FILL_JOB_INTERVAL_S      = 3_600   # her 1 sim saat
DISPATCH_ALGO_INTERVAL_S = 3_600   # her 1 sim saat (A-label bin'ler için yeterince sık)
ANOMALY_MIN_INTERVAL_S   = 300     # min 5 sim dakika
ANOMALY_MAX_INTERVAL_S   = 1_200   # max 20 sim dakika

ALGO_MAX_STOPS      = 40           # kapasite kırpması gerçek yük sınırını uygular
FIXED_ROUTE_SIZE    = 20            # 20 tane kutuya uğrar fixed rota
FIXED_DISPATCH_HOUR = 6            # her gün 06:00
MAX_FLEET_SIZE      = 12           # her dünya için maksimum aktif kamyon
MAX_FILL_HISTORY    = 10_000       # bellekte tutulacak maksimum fill event sayısı

EXTENSION_FILL_THRESHOLD     = 90.0   # % doluluk — mevcut kamyona ekleme eşiği
MAX_DETOUR_RATIO             = 0.30   # eklemenin kalan rotaya oranı ≤ %30
OPPORTUNISTIC_FILL_THRESHOLD = 55.0   # % doluluk — fırsatçı toplama eşiği (aynı zone)
FALLBACK_EMERGENCY_FILL      = 90.0   # fallback scatter sadece bu eşiğin üstü için

# ── ACO / HHO dinamik dispatch (Kim et al. 2023, Huang et al. 2026) ─────────
# lo_dcs her gün TÜM bin'leri gezen statik bir program (makale de statik);
# aco ve hho ise gerçekten doluluk-farkında/dinamik çalışır — sadece "must-go"
# bin'ler o gün rotalanır, boş bin'ler ziyaret edilmez.
DYNAMIC_TFL                = 80.0        # Threshold Fill Level — her iki makalede de 0.8
ACO_LOOKAHEAD_H            = 24.0        # estimation-based: bir sonraki güne kadar TFL'yi geçecekler de dahil
HHO_PREOPT_HOURS           = (9, 21)     # Huang'ın statik talep pencereleri sonu (7-9 / 19-21)
HHO_PREOPT_LOOKAHEAD_H     = 12.0        # bir sonraki pre-opt penceresine kadar
HHO_REOPT_INTERVAL_S       = 2 * 3_600   # periyodik yeniden-optimizasyon aralığı (makale Tablo 2: td=2h)
HHO_REOPT_MAX_DETOUR_RATIO = 0.30        # greedy insertion için maliyet/sapma kısıtı

# Tier-1: Acil zone
URGENT_ZONE_ETF_H    = 2.0   # ETF ≤ 2 saat → acil zone
URGENT_ZONE_MIN_BINS = 4     # minimum 4 bin

# Tier-2: Coverage rotation — ETF-bazlı adaptif interval (baz: 20 sim saat)
COVERAGE_INTERVAL_S  = 20 * 3_600  # baz interval; adaptif hesap için kullanılır
COVERAGE_MIN_FILL    = 50.0        # coverage turunda ≥50% dolu bin topla — yük/km'yi korur

# Koridor tabanlı fırsatçı toplama
CORRIDOR_RADIUS_KM        = 0.65   # rota bacağına 650m yakınındaki bin → aday
CORRIDOR_MIN_FILL         = 70.0   # koridor adayı için minimum doluluk
MAX_CORRIDOR_DETOUR_RATIO = 0.25   # koridor eklentisi için gevşek sapma oranı

# Coverage rotation — maksimum aralık tavanı
COVERAGE_MAX_INTERVAL_S   = 36 * 3_600  # 36 sim saat üzeri beklemeye izin verme

# Tier-0: Priority Aging — bekleyen bin'ler için ekstra kamyon
AGING_THRESHOLD_S    = 4 * 3_600   # 4 sim saat %100'de kaldıysa "yaşlı"
AGING_MIN_BINS       = 3           # ekstra kamyon tetiklemek için minimum yaşlı bin sayısı

# Gerçek sensör entegrasyonu (ESP32 firmware ile aynı geometri)
SENSOR_BIN_HEIGHT_CM  = 100.0      # ESP32-Sensor.ino BIN_HEIGHT_CM ile eşleşmeli
SENSOR_OFFSET_CM      = 3.0        # ESP32-Sensor.ino SENSOR_OFFSET_CM ile eşleşmeli
SENSOR_ENUM_FILL_PCT  = {          # median_distance_cm gönderilmediyse enum → temsili %
    "EMPTY":         0.0,
    "FULL":          75.0,          # 60–90% bandının ortası
    "CRITICAL_FULL": 95.0,          # 90–100% bandının ortası
}
SENSOR_ANOMALY_DURATION_S = 10 * 60  # SENSOR_ERROR için 10 sim-dakika anomali penceresi

SPEED_OPTIONS: dict[str, int] = {
    "1x": 1, "60x": 60, "3600x": 3600, "86400x": 86400,
}

# endregion


# =============================================================================
# region: VERİ SINIFLARI (BinState, TruckRoute)
# Simülasyonun iki temel veri yapısı burada tanımlanır.
# BinState — bir çöp kutusunun anlık durumunu (doluluk, anomali, taşma vb.) tutar.
# TruckRoute — seferdeki bir kamyonun rotasını, konumunu ve kapasitesini tutar.
# =============================================================================

@dataclass
class BinState:
    bin_id: str
    lat: float
    lon: float
    region: str
    fill_label: str          = "C"
    distance_label: int      = 2
    district_type: DistrictType = DistrictType.RESIDENTIAL  # Phase 1 — saatlik profil için
    fill_rate: float         = 1.0   # temel hız (%/sim-saat); etkin hız her tick hesaplanır
    fill_pct: float          = 0.0
    status: str              = "EMPTY"
    is_anomaly: bool         = False
    anomaly_end_sim_s: float = 0.0
    overflow_start_s: float  = -1.0  # ilk %100 geçiş sim_s; -1 = henüz taşmadı
    last_emptied_sim_s: float = -1.0 # son boşaltım sim_s; -1 = henüz boşaltılmadı

    def refresh_status(self) -> None:
        if self.is_anomaly:
            return
        if self.fill_pct >= CRITICAL_THRESHOLD:
            self.status = "CRITICAL_FULL"
        elif self.fill_pct >= FULL_THRESHOLD:
            self.status = "FULL"
        else:
            self.status = "EMPTY"

    def empty(self, sim_s: float = -1.0) -> None:
        self.last_emptied_sim_s = sim_s
        self.fill_pct           = 0.0
        self.is_anomaly         = False
        self.overflow_start_s   = -1.0
        self.status             = "EMPTY"


@dataclass
class TruckRoute:
    truck_id: int
    route_type: str
    stops: list               = field(default_factory=list)
    full_latlons: list        = field(default_factory=list)
    current_stop_idx: int     = 0
    lat: float                = 0.0
    lon: float                = 0.0
    from_lat: float           = 0.0
    from_lon: float           = 0.0
    to_lat: float             = 0.0
    to_lon: float             = 0.0
    leg_start_sim_s: float    = 0.0
    leg_end_sim_s: float      = 0.0
    service_end_sim_s: float  = 0.0
    status: str               = "en_route"
    at_bin: str | None        = None
    to_bin: str | None        = None
    progress: float           = 0.0
    capacity_used: float      = 0.0  # normalize [0, 1]; doluluk oranıyla artar

# endregion


# =============================================================================
# region: YARDIMCI FONKSİYONLAR (Geometri & Rota)
# Haversine mesafesi, nearest-neighbor sıralaması, 2-opt iyileştirmesi,
# ağırlığa duyarlı yakıt hesabı ve çeşitli mesafe/ekleme yardımcıları
# bu bölümde bulunur. Hiçbirinin yan etkisi yoktur; saf hesaplama işlevi görürler.
# =============================================================================

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R    = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a    = (math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
            * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(max(0.0, a)))


def _weighted_fuel(stops: list[Stop], depot_lat: float, depot_lon: float) -> tuple[float, float]:
    """
    Ağırlığa duyarlı yakıt hesabı.
    Kamyon her bin'i topladıkça ağır olur → yakıt sarfiyatı artar.
    Formül: fuel_per_km_i = FUEL_PER_KM * (1 + WEIGHT_MULTIPLIER * i/n)
    Dönüş bacağı: kamyon tamamen dolu → FUEL_PER_KM * (1 + WEIGHT_MULTIPLIER)
    """
    n          = len(stops)
    total_km   = 0.0
    total_fuel = 0.0
    prev_lat, prev_lon = depot_lat, depot_lon

    for i, stop in enumerate(stops):
        dist     = _haversine_km(prev_lat, prev_lon, stop.lat, stop.lon)
        w_factor = i / max(n, 1)          # 0 → 1 arası
        fuel_km  = FUEL_PER_KM * (1 + WEIGHT_MULTIPLIER * w_factor)
        total_km   += dist
        total_fuel += dist * fuel_km
        prev_lat, prev_lon = stop.lat, stop.lon

    # Dönüş bacağı — kamyon tamamen dolu
    dist_ret    = _haversine_km(prev_lat, prev_lon, depot_lat, depot_lon)
    total_km   += dist_ret
    total_fuel += dist_ret * FUEL_PER_KM * (1 + WEIGHT_MULTIPLIER)

    return total_km, total_fuel


def _remaining_route_km(truck: TruckRoute, depot_lat: float, depot_lon: float) -> float:
    """Kamyonun mevcut konumundan depot'a kadar kalan rota mesafesi (km)."""
    if truck.status == "returning":
        return _haversine_km(truck.lat, truck.lon, depot_lat, depot_lon)

    # Servis yapılıyorsa o durak tamamlanmış sayılır
    after_idx = truck.current_stop_idx + (1 if truck.status == "servicing" else 0)
    remaining = truck.stops[after_idx:]

    if not remaining:
        return _haversine_km(truck.lat, truck.lon, depot_lat, depot_lon)

    cur = truck.stops[truck.current_stop_idx]
    d   = _haversine_km(cur.lat, cur.lon, remaining[0].lat, remaining[0].lon)
    for i in range(len(remaining) - 1):
        d += _haversine_km(remaining[i].lat, remaining[i].lon,
                           remaining[i + 1].lat, remaining[i + 1].lon)
    d += _haversine_km(remaining[-1].lat, remaining[-1].lon, depot_lat, depot_lon)
    return d


def _insertion_km(
    truck: TruckRoute,
    new_stop: Stop,
    depot_lat: float,
    depot_lon: float,
) -> tuple[float, int]:
    """
    En ucuz ekleme noktasını ve ek km'yi döndür.

    Mevcut taahhüt edilen durağa müdahale edilmez (mid-leg yönlendirme yok).
    Geri dönüş bacağına da ekleme yapılabilir.

    Returns: (extra_km, insert_index_in_truck.stops)
    """
    if truck.status == "servicing":
        after_idx = truck.current_stop_idx + 1
        prev_lat  = truck.stops[truck.current_stop_idx].lat
        prev_lon  = truck.stops[truck.current_stop_idx].lon
    elif truck.status == "returning":
        after_idx = len(truck.stops)
        prev_lat, prev_lon = truck.lat, truck.lon
    else:  # en_route — mevcut hedef değiştirilemez
        after_idx = truck.current_stop_idx + 1
        prev_lat  = truck.stops[truck.current_stop_idx].lat
        prev_lon  = truck.stops[truck.current_stop_idx].lon

    remaining  = truck.stops[after_idx:]
    best_extra = float("inf")
    best_pos   = after_idx

    _pl, _plo = prev_lat, prev_lon
    for i, stop in enumerate(remaining):
        extra = (_haversine_km(_pl, _plo, new_stop.lat, new_stop.lon)
                 + _haversine_km(new_stop.lat, new_stop.lon, stop.lat, stop.lon)
                 - _haversine_km(_pl, _plo, stop.lat, stop.lon))
        if extra < best_extra:
            best_extra = extra
            best_pos   = after_idx + i
        _pl, _plo = stop.lat, stop.lon

    # Son durağın ardına (depot'tan önce) ekleme
    last_lat = remaining[-1].lat if remaining else prev_lat
    last_lon = remaining[-1].lon if remaining else prev_lon
    extra    = (_haversine_km(last_lat, last_lon, new_stop.lat, new_stop.lon)
                + _haversine_km(new_stop.lat, new_stop.lon, depot_lat, depot_lon)
                - _haversine_km(last_lat, last_lon, depot_lat, depot_lon))
    if extra < best_extra:
        best_extra = extra
        best_pos   = after_idx + len(remaining)

    return best_extra, best_pos


def _build_latlons(stops: list[Stop], depot_lat: float, depot_lon: float) -> list: #frontend için çizim noktalarını belirtiyor
    return [[depot_lat, depot_lon]] + [[s.lat, s.lon] for s in stops] + [[depot_lat, depot_lon]]


def _dist_to_segment_km(
    p_lat: float, p_lon: float,
    a_lat: float, a_lon: float,
    b_lat: float, b_lon: float,
) -> float:
    """Flat-earth yaklaşımıyla P noktasının A→B segmentine olan km mesafesi."""
    mid_lat = (a_lat + b_lat) / 2
    lat_km  = 111.0
    lon_km  = 111.0 * math.cos(math.radians(mid_lat))

    px = (p_lon - a_lon) * lon_km
    py = (p_lat - a_lat) * lat_km
    bx = (b_lon - a_lon) * lon_km
    by = (b_lat - a_lat) * lat_km

    seg_sq = bx * bx + by * by
    if seg_sq < 1e-10:
        return math.sqrt(px * px + py * py)

    t  = max(0.0, min(1.0, (px * bx + py * by) / seg_sq))
    dx = px - bx * t
    dy = py - by * t
    return math.sqrt(dx * dx + dy * dy)

# endregion


# =============================================================================
# region: SNAPSHOT YARDIMCILARI (_bin_to_dict, _truck_to_dict)
# Motor durumunu dışarıya (API / WebSocket) aktarmak için bin ve kamyon
# nesnelerini sözlüğe dönüştüren saf dönüşüm fonksiyonları.
# =============================================================================

def _bin_to_dict(b: BinState, sim_s: float, sim_epoch: datetime) -> dict:
    # Tahmini dolum vakti (virtual datetime)
    if b.fill_pct >= 100.0 or b.is_anomaly:
        estimated_full_iso = None
    elif b.fill_rate > 0:
        etf_h              = (100.0 - b.fill_pct) / b.fill_rate
        current_vt         = sim_epoch + timedelta(seconds=sim_s)
        estimated_full_iso = (current_vt + timedelta(hours=etf_h)).isoformat()
    else:
        estimated_full_iso = None  # dolmuyor

    # Son boşaltım vakti
    if b.last_emptied_sim_s >= 0:
        last_emptied_iso = (sim_epoch + timedelta(seconds=b.last_emptied_sim_s)).isoformat()
    else:
        last_emptied_iso = None

    return {
        "bin_id":             b.bin_id,
        "lat":                b.lat,
        "lon":                b.lon,
        "region":             b.region,
        "fill_pct":           round(b.fill_pct, 1),
        "status":             b.status,
        "fill_label":         b.fill_label,
        "fill_rate":          b.fill_rate,
        "distance_label":     b.distance_label,
        "district_type":      b.district_type.value,
        "estimated_full_iso": estimated_full_iso,
        "last_emptied_iso":   last_emptied_iso,
    }


def _truck_to_dict(t: TruckRoute, depot_lat: float, depot_lon: float) -> dict:
    remaining   = [[s.lat, s.lon] for s in t.stops[t.current_stop_idx:]]
    route_ahead = [[round(t.lat, 6), round(t.lon, 6)]] + remaining + [[depot_lat, depot_lon]]
    return {
        "truck_id":         t.truck_id,
        "route_type":       t.route_type,
        "status":           t.status,
        "lat":              round(t.lat, 6),
        "lon":              round(t.lon, 6),
        "at_bin":           t.at_bin,
        "to_bin":           t.to_bin,
        "progress":         round(t.progress, 3),
        "stops_total":      len(t.stops),
        "current_stop_idx": t.current_stop_idx,
        "full_latlons":     t.full_latlons,
        "route_ahead":      route_ahead,
        "capacity_used":    round(t.capacity_used, 3),
    }

# endregion


# =============================================================================
# region: SimulationEngine — SINIF TANIMI
# Tüm simülasyon mantığını kapsayan singleton sınıf.
# Alt bölümler aşağıdaki sırayla devam eder:
#   • __init__ ve genel yardımcılar
#   • Veri yükleme (load_bins, depot, fixed routes)
#   • Kontrol (start / stop / reset)
#   • Ana döngü (_loop)
#   • Fill job
#   • Sensör enjeksiyonu
#   • Rota genişletme (koridor + extension)
#   • Dispatch — Algo (DPET)
#   • Dispatch — Fixed (sabit rota)
#   • Kamyon oluşturma
#   • Kamyon ilerlemesi
#   • Event job (Phase 1)
#   • Fill history logger
#   • Anomaly job + healing
#   • Snapshot metodları
# =============================================================================

class SimulationEngine:
    """Singleton."""

    # =========================================================================
    # region: __init__ ve Genel Yardımcılar
    # Motor nesnesinin ilk durumu ve sıfırlama/yardımcı statik metodlar.
    # =========================================================================

    def __init__(self) -> None:
        self.is_running       = False
        self.speed_multiplier = 3600

        self._sim_epoch = datetime(2024, 1, 1, tzinfo=timezone.utc)
        self._sim_s: float = 0.0

        self.depot_lat: float = _DEFAULT_DEPOT_LAT
        self.depot_lon: float = _DEFAULT_DEPOT_LON

        self.algo_bins:  dict[str, BinState] = {}
        self.fixed_bins: dict[str, BinState] = {}

        self.algo_trucks:  list[TruckRoute] = []
        self.fixed_trucks: list[TruckRoute] = []

        self.algo_kpis  = self._zero_kpis()
        self.fixed_kpis = self._zero_kpis()

        self.recent_anomalies: list[dict] = []
        self.fill_history:     list[dict] = []
        self._event_manager    = EventManager()
        self._predictor        = FillPredictor()
        self._last_zone_visit: dict[int, float] = {}   # zone_id → son ziyaret sim_s
        self._fixed_routes: list[list[Stop]] = []
        self.fixed_algorithm: str = DEFAULT_FIXED_ALGORITHM

        self._last_fill_s: float           = -FILL_JOB_INTERVAL_S
        self._last_dispatch_algo_s: float  = -DISPATCH_ALGO_INTERVAL_S
        self._last_fixed_day_key: tuple | None = None
        self._fixed_route_cursor: int      = 0   # o gün kaçıncı rotadan devam edilecek
        self._last_hho_preopt_key: tuple | None = None   # (yıl,ay,gün,saat) — HHO pre-opt tetikleyici
        self._last_hho_reopt_s: float      = -HHO_REOPT_INTERVAL_S  # HHO periyodik re-opt tetikleyici
        self._next_anomaly_s: float        = self._rand_anomaly_s()

        self._truck_ctr: int = 0
        self._task: asyncio.Task | None = None

    @staticmethod
    def _zero_kpis() -> dict: #temiz sayfa ile başlatıyor
        return {
            "distance_km": 0.0, "fuel_l": 0.0, "co2_kg": 0.0,
            "cost_tl": 0.0, "dispatch_count": 0, "overflow_events": 0,
            "overflow_count": 0, "bins_collected": 0, "load_collected": 0.0,
        }

    @staticmethod #random anomaly tetikliyor rastgele  binlerde
    def _rand_anomaly_s() -> float:
        return random.uniform(ANOMALY_MIN_INTERVAL_S, ANOMALY_MAX_INTERVAL_S)

    @property
    def virtual_clock(self) -> datetime:
        return self._sim_epoch + timedelta(seconds=self._sim_s)

    # endregion

    # =========================================================================
    # region: Veri Yükleme (load_bins, Depot, Fixed Routes)
    # Bin listesini yükler, depot konumunu hesaplar ve sabit rotaları
    # Sweep heuristic + 2-opt ile startup'ta bir kez önceden oluşturur.
    # =========================================================================

    def load_bins(self, bin_rows: list[dict]) -> None:
        self.algo_bins.clear()
        self.fixed_bins.clear()
        for row in bin_rows:
            bid   = row["bin_id"]
            label = row.get("fill_label") or "C"
            lo, hi = FILL_RATE_RANGES.get(label, (0.8, 2.0))
            fill_rate = round(random.uniform(lo, hi), 3)

            region = row.get("region") or "Unknown"
            common = dict(
                bin_id         = bid,
                lat            = float(row["lat"]),
                lon            = float(row["lon"]),
                region         = region,
                fill_label     = label,
                distance_label = int(row.get("distance_label") or 2),
                district_type  = assign_district(region),   # Phase 1
                fill_rate      = fill_rate,
            )
            self.algo_bins[bid]  = BinState(**common)
            # Her iki dünya aynı fill_rate'i paylaşır (bin fiziksel olarak aynı)
            self.fixed_bins[bid] = BinState(**common)
        self._compute_depot()
        self._precompute_fixed_routes()
        self._predictor.assign_zones(list(self.algo_bins.values()))

    def _compute_depot(self) -> None:
        if not self.algo_bins:
            return
        northernmost   = max(self.algo_bins.values(), key=lambda b: b.lat)
        self.depot_lat = round(northernmost.lat + DEPOT_NORTH_OFFSET, 6)
        self.depot_lon = round(northernmost.lon, 6)

    def _precompute_fixed_routes(self) -> None:
        """
        Yalnızca `lo_dcs` için geçerli: tüm bin'leri kapsayan statik günlük
        program bir kez önceden hesaplanır (Goswami et al. 2026 — makalenin
        kendisi de statik, tek seferlik bir VRP çözümü).

        `aco` ve `hho` doluluk-farkında/dinamik çalışır (bkz.
        _job_dispatch_fixed_aco_dynamic / _job_dispatch_fixed_hho_dynamic) —
        rotalar her dispatch döngüsünde o anki "must-go" bin kümesine göre
        anlık kurulur, burada önceden hesaplanacak sabit bir şey yoktur.
        """
        self._fixed_routes.clear()
        if self.fixed_algorithm != "lo_dcs":
            return

        all_bins = list(self.fixed_bins.values())
        if not all_bins:
            return

        k = math.ceil(len(all_bins) / FIXED_ROUTE_SIZE)
        for cluster in kmeans_clusters(all_bins, k):
            route = lo_dcs_route(cluster, self.depot_lat, self.depot_lon)
            if route:
                self._fixed_routes.append(route)

    def set_fixed_algorithm(self, algorithm: str) -> bool:
        """
        Fixed dünyasının rota kurma algoritmasını değiştir. `lo_dcs` seçilirse
        statik program hemen yeniden hesaplanır; `aco`/`hho` için hesaplama
        dispatch döngüsünde dinamik olarak yapılacağından burada iş yoktur.
        Simülasyon çalışırken çağrılamaz — sağdaki dropdown bu yüzden
        is_running iken devre dışı bırakılır (bkz. routers/simulation.py).

        Returns: başarılıysa True, geçersiz algoritma adında veya simülasyon
        çalışırken çağrılırsa False.
        """
        if self.is_running or algorithm not in FIXED_ROUTE_ALGORITHMS:
            return False
        self.fixed_algorithm = algorithm
        self._precompute_fixed_routes()
        self.fixed_trucks.clear()
        self.fixed_kpis           = self._zero_kpis()
        self._fixed_route_cursor  = 0
        self._last_fixed_day_key  = None
        self._last_hho_preopt_key = None
        self._last_hho_reopt_s    = -HHO_REOPT_INTERVAL_S
        return True

    # endregion

    # =========================================================================
    # region: Kontrol (start / stop / reset)
    # Motorun asyncio görevini başlatır, durdurur ve başlangıç durumuna alır.
    # =========================================================================

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
            b.fill_pct          = 0.0
            b.status            = "EMPTY"
            b.is_anomaly        = False
            b.anomaly_end_sim_s = 0.0
        self.algo_trucks.clear()
        self.fixed_trucks.clear()
        self.algo_kpis  = self._zero_kpis()
        self.fixed_kpis = self._zero_kpis()
        self.recent_anomalies.clear()
        self.fill_history.clear()
        self._event_manager.reset()
        self._predictor.reset()
        self._last_zone_visit.clear()
        self._sim_s                = 0.0
        self._last_fill_s          = -FILL_JOB_INTERVAL_S
        self._last_dispatch_algo_s = -DISPATCH_ALGO_INTERVAL_S
        self._last_fixed_day_key   = None
        self._fixed_route_cursor   = 0
        self._last_hho_preopt_key  = None
        self._last_hho_reopt_s     = -HHO_REOPT_INTERVAL_S
        self._next_anomaly_s       = self._rand_anomaly_s()
        self._truck_ctr            = 0

    # endregion

    # =========================================================================
    # region: Ana Döngü (_loop)
    # Her 0.2 gerçek saniyede bir tüm job'ları sırayla tetikler.
    # speed_multiplier ile simülasyon zamanı gerçek zamandan hızlı akar.
    # =========================================================================

    TICK_REAL_S = 0.2

    async def _loop(self) -> None:
        while self.is_running:
            self._sim_s += self.TICK_REAL_S * self.speed_multiplier
            self._job_events()           # Phase 1 — event üret/temizle
            self._job_fill()
            self._job_dispatch_algo()
            self._job_dispatch_fixed()
            self._job_anomaly()
            self._heal_anomalies()
            self._advance_trucks()
            await asyncio.sleep(self.TICK_REAL_S)

    # endregion

    # =========================================================================
    # region: Fill Job
    # Her 1 sim saatte bir tüm bin'lerin doluluk yüzdesini artırır.
    # Her iki dünya (algo / fixed) için bağımsız taşma (overflow) sayımı yapar.
    # Phase 1: etkin dolma hızı saatlik profil × event × gürültü formülüyle hesaplanır.
    # =========================================================================

    def _job_fill(self) -> None:
        if self._sim_s - self._last_fill_s < FILL_JOB_INTERVAL_S:
            return
        self._last_fill_s = self._sim_s

        hour   = self.virtual_clock.hour
        events = self._event_manager.active(self._sim_s)   # Phase 1

        for world, kpis, world_name in (
            (self.algo_bins,  self.algo_kpis,  "algo"),
            (self.fixed_bins, self.fixed_kpis, "fixed"),
        ):
            for b in world.values():
                if b.is_anomaly:
                    continue

                # Phase 1: saatlik profil + event + gürültü ile etkin hız
                rate = effective_fill_rate(b.fill_rate, b.district_type, hour, events)

                old_pct    = b.fill_pct
                b.fill_pct = min(100.0, b.fill_pct + rate)

                if b.fill_pct >= 100.0:
                    kpis["overflow_events"] += 1
                    if old_pct < 100.0:
                        kpis["overflow_count"] += 1   # yeni taşma olayı (%100'e ilk geçiş)
                        self._append_history("OVERFLOW", b, world_name)
                    # İlk kez %100'e ulaştığında zamanı kaydet (aging için)
                    if world_name == "algo" and b.overflow_start_s < 0:
                        b.overflow_start_s = self._sim_s
                b.refresh_status()

    # endregion

    # =========================================================================
    # region: Sensör Enjeksiyonu (inject_sensor_reading)
    # ESP32 sensöründen gelen anlık ölçümü her iki dünyadaki bin state'ine yazar.
    # Sentetik dolma modelini override eder; SENSOR_ERROR anomali olarak işlenir.
    # =========================================================================

    def inject_sensor_reading(
        self,
        bin_id: str,
        enum_state: str,
        median_distance_cm: float | None = None,
    ) -> None:
        """
        ESP32 sensöründen gelen anlık ölçümü hem algo hem fixed dünyasındaki bin
        state'ine eşitler. Sentetik dolma modelini override eder; bir sonraki
        _job_fill çağrısı bu noktadan devam eder.

        - median_distance_cm verilirse firmware ile aynı formülle fill_pct hesaplanır.
        - Aksi hâlde enum → temsili yüzde haritalaması uygulanır.
        - %100'e geçişler overflow sayacına işlenir, fill_history'ye OVERFLOW eklenir.
        - Yüksek doluluktan EMPTY'ye düşüş last_emptied_sim_s'i set eder.
        - SENSOR_ERROR durumunda bin anomali olarak işaretlenir + recent_anomalies'e
          push edilir, böylece canlı panoda anında görünür.
        """
        if not self.algo_bins and not self.fixed_bins:
            return  # engine henüz yüklenmedi

        # SENSOR_ERROR → her iki dünyada anomali pencere aç, fill_pct'e dokunma
        if enum_state == "SENSOR_ERROR":
            end_s = self._sim_s + SENSOR_ANOMALY_DURATION_S
            for world in (self.algo_bins, self.fixed_bins):
                b = world.get(bin_id)
                if b is None:
                    continue
                b.status            = "SENSOR_ERROR"
                b.is_anomaly        = True
                b.anomaly_end_sim_s = end_s
            self._push_sensor_anomaly(bin_id, "SENSOR_NOT_FOUND_ERROR")
            return

        # Fill yüzdesini hesapla
        if median_distance_cm is not None and median_distance_cm > 0:
            effective = max(0.0, median_distance_cm - SENSOR_OFFSET_CM)
            filled    = max(0.0, min(SENSOR_BIN_HEIGHT_CM,
                                     SENSOR_BIN_HEIGHT_CM - effective))
            fill_pct  = (filled / SENSOR_BIN_HEIGHT_CM) * 100.0
        else:
            fill_pct  = SENSOR_ENUM_FILL_PCT.get(enum_state, 0.0)

        fill_pct = max(0.0, min(100.0, fill_pct))

        for world, kpis, world_name in (
            (self.algo_bins,  self.algo_kpis,  "algo"),
            (self.fixed_bins, self.fixed_kpis, "fixed"),
        ):
            b = world.get(bin_id)
            if b is None:
                continue

            old_pct = b.fill_pct

            # Gerçek ölçüm geldi → varsa anomaly state'ini kapat
            b.is_anomaly        = False
            b.anomaly_end_sim_s = 0.0
            b.fill_pct          = fill_pct

            # Yüksek doluluktan boşa düşüş → boşaltıldı say
            if old_pct >= FULL_THRESHOLD and fill_pct < FULL_THRESHOLD:
                b.empty(self._sim_s)
                self._append_history("EMPTIED", b, world_name)
                continue

            # Yeni %100 geçişi → overflow logla
            if fill_pct >= 100.0 and old_pct < 100.0:
                kpis["overflow_count"]  += 1
                kpis["overflow_events"] += 1
                if world_name == "algo" and b.overflow_start_s < 0:
                    b.overflow_start_s = self._sim_s
                self._append_history("OVERFLOW", b, world_name)

            b.refresh_status()

    def _push_sensor_anomaly(self, bin_id: str, event_type: str) -> None:
        """Canlı pano akışı için recent_anomalies kuyruğuna kayıt ekler."""
        self.recent_anomalies.append({
            "bin_id":       bin_id,
            "event_type":   event_type,
            "virtual_time": self.virtual_clock.isoformat(),
            "details":      f"{event_type} @ {bin_id} (real sensor)",
        })
        if len(self.recent_anomalies) > 50:
            self.recent_anomalies.pop(0)

    # endregion

    # =========================================================================
    # region: Rota Genişletme (_corridor_bins, _try_extend_truck)
    # Yeni dispatch açmadan önce acil bin'leri mevcut kamyonlara ekler.
    # Koridor mantığı: rota bacaklarına yakın ve yeterince dolu bin'ler
    # minimum sapma maliyetiyle aktif kamyonun rotasına eklenir.
    # =========================================================================

    def _corridor_bins(self, available: dict, excluded: set[str]) -> list[BinState]:
        """
        Aktif kamyon rotalarının bacaklarına CORRIDOR_RADIUS_KM'den yakın ve
        CORRIDOR_MIN_FILL üzerindeki bin'leri bul.

        Rota üzerinden geçerken "bedavaya" toplanabilecek bin'leri döndürür.
        """
        candidates: set[str] = set()
        for truck in self.algo_trucks:
            if truck.status == "done":
                continue
            # Bacak noktaları: mevcut konum → kalan duraklar
            waypoints: list[tuple[float, float]] = [(truck.lat, truck.lon)]
            for stop in truck.stops[truck.current_stop_idx:]:
                waypoints.append((stop.lat, stop.lon))

            for i in range(len(waypoints) - 1):
                a_lat, a_lon = waypoints[i]
                b_lat, b_lon = waypoints[i + 1]
                for bid, b in available.items():
                    if bid in excluded or bid in candidates:
                        continue
                    if b.is_anomaly or b.fill_pct < CORRIDOR_MIN_FILL:
                        continue
                    if _dist_to_segment_km(b.lat, b.lon, a_lat, a_lon, b_lat, b_lon) <= CORRIDOR_RADIUS_KM:
                        candidates.add(bid)

        return [available[bid] for bid in candidates if bid in available]

    def _try_extend_truck(
        self,
        urgent_bins: list[BinState],
        max_detour: float = MAX_DETOUR_RATIO,
        *,
        truck_list: list[TruckRoute] | None = None,
        kpis: dict | None = None,
    ) -> set[str]:
        """
        Bin listesini mevcut aktif kamyonlara eklemeye çalış.

        Her bin için en düşük sapmalı ve kapasitesi yeterli kamyonu bul.
        max_detour aşılırsa ya da kapasite yoksa yeni kamyon dispatch'e bırakılır.

        Varsayılan olarak algo (DPET) dünyasını hedefler; HHO'nun periyodik
        re-optimization fazı bu metodu fixed dünyası için `truck_list`/`kpis`
        vererek yeniden kullanır (bkz. _hho_reopt) — makalenin "greedy
        insertion" + kapasite/maliyet kısıtı mantığı aynen budur.

        Returns: başarıyla eklenen bin_id'leri.
        """
        truck_list = self.algo_trucks if truck_list is None else truck_list
        kpis       = self.algo_kpis if kpis is None else kpis
        extended: set[str] = set()

        for b in urgent_bins:
            new_stop = Stop(b.bin_id, b.lat, b.lon)
            bin_load = (b.fill_pct / 100.0) * BIN_VOLUME_FRACTION

            best_truck      = None
            best_extra_km   = float("inf")
            best_insert_pos = -1

            for truck in truck_list:
                if truck.status == "done":
                    continue
                if TRUCK_CAPACITY - truck.capacity_used < bin_load:
                    continue

                rem_km = _remaining_route_km(truck, self.depot_lat, self.depot_lon)
                if rem_km < 0.1:
                    continue

                extra_km, pos = _insertion_km(truck, new_stop, self.depot_lat, self.depot_lon)
                if extra_km / rem_km <= max_detour and extra_km < best_extra_km:
                    best_extra_km   = extra_km
                    best_truck      = truck
                    best_insert_pos = pos

            if best_truck is not None:
                best_truck.stops.insert(best_insert_pos, new_stop)
                best_truck.full_latlons = _build_latlons(
                    best_truck.stops, self.depot_lat, self.depot_lon
                )
                extended.add(b.bin_id)

                # Ek mesafe için KPI güncelle (tahmini %75 yük faktörü)
                extra_fuel = best_extra_km * FUEL_PER_KM * (1 + WEIGHT_MULTIPLIER * 0.75)
                kpis["distance_km"] += best_extra_km
                kpis["fuel_l"]      += extra_fuel
                kpis["co2_kg"]      += best_extra_km * CO2_PER_KM
                kpis["cost_tl"]     += extra_fuel * FUEL_PRICE_TL

        return extended

    # endregion

    # =========================================================================
    # region: Dispatch — Algo (DPET)
    # Her 1 sim saatte bir DPET algoritmasını çalıştırır.
    # Üç kademeli önceliklendirme:
    #   Tier-0 — Priority Aging: 4+ saat %100'de bekleyen bin'ler için ekstra kamyon.
    #   Tier-1 — Acil zone: ETF ≤ 2 saat olan zone'lar önce gönderilir.
    #   Tier-2 — Coverage Rotation: ETF-bazlı adaptif aralıkla zone döngüsü.
    # Fallback: Tier 0-2 boşsa ve ≥90% bin varsa doğrudan emergency dispatch.
    # =========================================================================

    def _job_dispatch_algo(self) -> None:
        if self._sim_s - self._last_dispatch_algo_s < DISPATCH_ALGO_INTERVAL_S:
            return
        self._last_dispatch_algo_s = self._sim_s

        # Aktif kamyonlarda zaten durağı olan bin'leri hariç tut
        claimed   = self._active_stop_bin_ids(self.algo_trucks)
        available = {b.bin_id: b for b in self.algo_bins.values() if b.bin_id not in claimed}

        # Acil bin'leri önce mevcut kamyonlara eklemeye çalış (yeni sefer açmadan)
        urgent       = [b for b in available.values()
                        if b.fill_pct >= EXTENSION_FILL_THRESHOLD and not b.is_anomaly]
        extended_ids = self._try_extend_truck(urgent) if urgent and self.algo_trucks else set()

        # Koridor fırsatçı toplama: rota bacaklarına yakın bin'ler — her zaman aktif
        if self.algo_trucks:
            corridor = self._corridor_bins(available, claimed | extended_ids)
            if corridor:
                extended_ids |= self._try_extend_truck(corridor, MAX_CORRIDOR_DETOUR_RATIO)

        available    = {bid: b for bid, b in available.items() if bid not in extended_ids}

        dispatched_ids: set[str] = set()

        def _dispatch_zone_bins(zone_id: int, zone_bins: list) -> None:
            """Zone bin listesini fırsatçı toplama ile gönder; son ziyareti güncelle."""
            if len(self.algo_trucks) >= MAX_FLEET_SIZE:
                return
            anchor_ids    = {b.bin_id for b in zone_bins}
            opportunistic = [
                b for bid, b in available.items()
                if bid not in anchor_ids
                and bid not in dispatched_ids
                and not b.is_anomaly
                and b.fill_pct >= OPPORTUNISTIC_FILL_THRESHOLD
                and self._predictor.zone_of(bid) == zone_id
            ]
            combined = [b for b in zone_bins if b.bin_id not in dispatched_ids] + opportunistic
            if not combined:
                return
            routes = dpet_dispatch(
                bins               = combined,
                active_truck_count = len(self.algo_trucks),
                hour               = self.virtual_clock.hour,
                depot_lat          = self.depot_lat,
                depot_lon          = self.depot_lon,
                max_fleet          = MAX_FLEET_SIZE,
                max_stops          = ALGO_MAX_STOPS,
            )
            for route in routes:
                self._create_truck("algo", route, self.algo_trucks, self.algo_kpis)
                dispatched_ids.update(s.bin_id for s in route)
            self._last_zone_visit[zone_id] = self._sim_s

        # Tier-0 — Priority Aging
        aged_bins = [
            b for b in available.values()
            if b.overflow_start_s >= 0
            and self._sim_s - b.overflow_start_s >= AGING_THRESHOLD_S
            and not b.is_anomaly
        ]
        if len(aged_bins) >= AGING_MIN_BINS and len(self.algo_trucks) < MAX_FLEET_SIZE:
            routes = dpet_dispatch(
                bins               = aged_bins,
                active_truck_count = len(self.algo_trucks),
                hour               = self.virtual_clock.hour,
                depot_lat          = self.depot_lat,
                depot_lon          = self.depot_lon,
                max_fleet          = MAX_FLEET_SIZE,
                max_stops          = ALGO_MAX_STOPS,
            )
            for route in routes:
                self._create_truck("algo", route, self.algo_trucks, self.algo_kpis)
                dispatched_ids.update(s.bin_id for s in route)

        # Tier-1 — Acil zone (ETF ≤ 2 saat, taşmayı önle)
        urgent_zones = self._predictor.urgent_zone_bins(
            available, URGENT_ZONE_ETF_H, URGENT_ZONE_MIN_BINS
        )
        for zone_id, zone_bins in urgent_zones.items():
            _dispatch_zone_bins(zone_id, zone_bins)

        # Tier-2 — Coverage Rotation (ETF-bazlı adaptif interval)
        for zone_id in range(self._predictor.n_zones()):
            if len(self.algo_trucks) >= MAX_FLEET_SIZE:
                break
            if zone_id in urgent_zones:
                continue  # Tier-1'de zaten işlendi
            last_visit        = self._last_zone_visit.get(zone_id, -COVERAGE_INTERVAL_S)
            adaptive_interval = self._predictor.adaptive_coverage_interval_s(
                zone_id, available, COVERAGE_INTERVAL_S
            )
            if self._sim_s - last_visit < adaptive_interval:
                continue
            zone_bins = self._predictor.coverage_zone_bins(
                available, zone_id, COVERAGE_MIN_FILL
            )
            if zone_bins:
                _dispatch_zone_bins(zone_id, zone_bins)
            else:
                # Toplayacak bir şey yok; zone ziyaret edilmiş say
                self._last_zone_visit[zone_id] = self._sim_s

        # Fallback — hiç dispatch yoksa ve ≥90% bin varsa
        if not dispatched_ids:
            emergency = [
                b for b in available.values()
                if b.fill_pct >= FALLBACK_EMERGENCY_FILL
                and not b.is_anomaly
            ]
            if emergency:
                routes = dpet_dispatch(
                    bins               = emergency,
                    active_truck_count = len(self.algo_trucks),
                    hour               = self.virtual_clock.hour,
                    depot_lat          = self.depot_lat,
                    depot_lon          = self.depot_lon,
                    max_fleet          = MAX_FLEET_SIZE,
                    max_stops          = ALGO_MAX_STOPS,
                )
                for route in routes:
                    self._create_truck("algo", route, self.algo_trucks, self.algo_kpis)

    # endregion

    # =========================================================================
    # region: Dispatch — Fixed (Sabit Rota / Dinamik Rota)
    # Seçili algoritmaya göre üç farklı davranış:
    #   lo_dcs : Her gün 06:00'da precompute edilmiş STATİK programı sırayla
    #            devreye alır (Goswami et al. 2026 — makale de statik).
    #   aco    : Her gün 06:00'da o anki doluluğa göre "must-go" bin'leri
    #            seçip anında K-Means+ACO ile rotalar (Kim et al. 2023 —
    #            estimation-based collection approach).
    #   hho    : Günde iki kez (09:00/21:00) pre-optimization + periyodik
    #            (2 sim-saatte bir) re-optimization ile TEK filoya uyarlanmış
    #            iki fazlı dinamik dispatch (Huang et al. 2026).
    # =========================================================================

    def _job_dispatch_fixed(self) -> None:
        if self.fixed_algorithm == "lo_dcs":
            self._job_dispatch_fixed_static()
        elif self.fixed_algorithm == "aco":
            self._job_dispatch_fixed_aco_dynamic()
        elif self.fixed_algorithm == "hho":
            self._job_dispatch_fixed_hho_dynamic()

    def _job_dispatch_fixed_static(self) -> None:
        """lo_dcs — her gün 06:00'da precompute edilmiş sabit rotaları sırayla devreye alır."""
        vc = self.virtual_clock
        if vc.hour < FIXED_DISPATCH_HOUR:
            return
        day_key = (vc.year, vc.month, vc.day)
        if self._last_fixed_day_key == day_key:
            return
        self._last_fixed_day_key = day_key

        # Yeni gün: imleci sıfırla, ilk kamyon grubunu yola çıkar
        self._fixed_route_cursor = 0
        for _ in range(min(MAX_FLEET_SIZE, len(self._fixed_routes))):
            self._dispatch_next_fixed_route()

    def _dispatch_next_fixed_route(self) -> None:
        """Sıradaki sabit rotayı gönder; filo doluysa ya da rota kalmadıysa dur (lo_dcs)."""
        if self._fixed_route_cursor >= len(self._fixed_routes):
            return
        if len(self.fixed_trucks) >= MAX_FLEET_SIZE:
            return
        route = self._fixed_routes[self._fixed_route_cursor]
        self._fixed_route_cursor += 1
        if route:
            self._create_truck("fixed", route, self.fixed_trucks, self.fixed_kpis)

    def _must_go_bins(self, lookahead_h: float) -> list[BinState]:
        """
        DYNAMIC_TFL üzerindeki VEYA ETF'i lookahead_h içinde TFL'yi geçecek
        (henüz aktif bir kamyona atanmamış, anomali olmayan) bin'leri döndürür.

        Kim'in "estimation-based collection approach"ının (Section 3.3.1) bu
        simülasyona uyarlanmış hâli — orada istatistiksel bir tahmin formülü
        (Ŵit) kullanılıyor; burada fill_rate zaten kesin bilindiğinden ETF
        doğrudan hesaplanabiliyor (gerçek sensör belirsizliği yerine
        simülasyonun kendi zemin-gerçeği kullanılıyor).
        """
        claimed = self._active_stop_bin_ids(self.fixed_trucks)
        must_go: list[BinState] = []
        for b in self.fixed_bins.values():
            if b.bin_id in claimed or b.is_anomaly:
                continue
            if b.fill_pct >= DYNAMIC_TFL:
                must_go.append(b)
            elif b.fill_rate > 0:
                etf = (100.0 - b.fill_pct) / b.fill_rate
                if etf <= lookahead_h:
                    must_go.append(b)
        return must_go

    def _dispatch_must_go_bins(self, must_go: list[BinState], build_route) -> None:
        """K-Means ile kapasite büyüklüğünde kümele, her kümeyi build_route ile rotala."""
        if not must_go:
            return
        k = math.ceil(len(must_go) / FIXED_ROUTE_SIZE)
        for cluster in kmeans_clusters(must_go, k):
            if len(self.fixed_trucks) >= MAX_FLEET_SIZE:
                break
            route = build_route(cluster, self.depot_lat, self.depot_lon)
            if route:
                self._create_truck("fixed", route, self.fixed_trucks, self.fixed_kpis)

    def _job_dispatch_fixed_aco_dynamic(self) -> None:
        """
        aco — Kim et al. (2023), estimation-based collection approach.

        Her gün 06:00'da doluluğu TFL üzerinde olan VEYA ETF'i bir sonraki
        dispatch'e kadar TFL'yi geçecek "must-go" bin'ler seçilir; sadece
        onlar K-Means + ACO ile rotalanır. Boş/az dolu bin'ler o gün hiç
        ziyaret edilmez — lo_dcs'in aksine gerçekten doluluk-farkında.
        """
        vc = self.virtual_clock
        if vc.hour < FIXED_DISPATCH_HOUR:
            return
        day_key = (vc.year, vc.month, vc.day)
        if self._last_fixed_day_key == day_key:
            return
        self._last_fixed_day_key = day_key

        self._dispatch_must_go_bins(self._must_go_bins(ACO_LOOKAHEAD_H), aco_route)

    def _job_dispatch_fixed_hho_dynamic(self) -> None:
        """hho — Huang et al. (2026), tek filoya uyarlanmış iki fazlı dinamik dispatch."""
        self._hho_preopt()
        self._hho_reopt()

    def _hho_preopt(self) -> None:
        """
        Faz 1 — Pre-optimization: günde iki kez (HHO_PREOPT_HOURS = 09:00/21:00,
        makalenin statik talep pencereleri sonu), must-go bin'ler K-Means +
        Improved HHO ile rotalanıp yeni kamyonlar olarak gönderilir.
        """
        vc = self.virtual_clock
        if vc.hour not in HHO_PREOPT_HOURS:
            return
        key = (vc.year, vc.month, vc.day, vc.hour)
        if self._last_hho_preopt_key == key:
            return
        self._last_hho_preopt_key = key

        self._dispatch_must_go_bins(self._must_go_bins(HHO_PREOPT_LOOKAHEAD_H), hho_route)

    def _hho_reopt(self) -> None:
        """
        Faz 2 — Re-optimization: her HHO_REOPT_INTERVAL_S (makale Tablo 2:
        td=2h) sim-saatte bir, TFL'yi yeni geçen bin'ler mevcut aktif
        kamyonlara maliyet/kapasite kısıtı içinde eklenmeye çalışılır (greedy
        insertion — makalenin Section 3.3 "capacity/cost constraint" mantığı).

        Eklenemeyen bin, bir sonraki pre-opt penceresinde otomatik olarak
        must-go listesine girer — ayrı bir "dış kaynak filo" kavramımız
        olmadığından, makaledeki outsourced-vehicle fallback'inin yerini bu
        bekleme alır (tek filo modeline uyarlanmış hâli).
        """
        if self._sim_s - self._last_hho_reopt_s < HHO_REOPT_INTERVAL_S:
            return
        self._last_hho_reopt_s = self._sim_s

        if not self.fixed_trucks:
            return   # eklenecek aktif rota yok — bir sonraki pre-opt'a kalır

        claimed    = self._active_stop_bin_ids(self.fixed_trucks)
        candidates = [
            b for b in self.fixed_bins.values()
            if b.bin_id not in claimed and not b.is_anomaly and b.fill_pct >= DYNAMIC_TFL
        ]
        if candidates:
            self._try_extend_truck(
                candidates,
                HHO_REOPT_MAX_DETOUR_RATIO,
                truck_list=self.fixed_trucks,
                kpis=self.fixed_kpis,
            )

    # endregion

    # =========================================================================
    # region: Kamyon Oluşturma (_create_truck)
    # Yeni bir TruckRoute nesnesi oluşturur, ilk bacağı hesaplar ve KPI'leri günceller.
    # Ağırlığa duyarlı yakıt modeli burada rota toplamı olarak hesaplanır.
    # =========================================================================

    def _create_truck(
        self,
        route_type: str,
        stops: list[Stop],
        truck_list: list[TruckRoute],
        kpis: dict,
    ) -> None:
        if not stops:
            return

        self._truck_ctr += 1
        first        = stops[0]
        dist_first   = _haversine_km(self.depot_lat, self.depot_lon, first.lat, first.lon)
        travel_first = (dist_first / TRUCK_SPEED_KMH) * 3600

        truck = TruckRoute(
            truck_id        = self._truck_ctr,
            route_type      = route_type,
            stops           = stops,
            full_latlons    = _build_latlons(stops, self.depot_lat, self.depot_lon),
            lat             = self.depot_lat,
            lon             = self.depot_lon,
            from_lat        = self.depot_lat,
            from_lon        = self.depot_lon,
            to_lat          = first.lat,
            to_lon          = first.lon,
            leg_start_sim_s = self._sim_s,
            leg_end_sim_s   = self._sim_s + travel_first,
            to_bin          = first.bin_id,
            status          = "en_route",
        )
        truck_list.append(truck)

        # Ağırlığa duyarlı yakıt ve mesafe
        total_km, total_fuel = _weighted_fuel(stops, self.depot_lat, self.depot_lon)
        co2  = total_km * CO2_PER_KM
        cost = DISPATCH_COST_TL + total_fuel * FUEL_PRICE_TL

        kpis["distance_km"]    += total_km
        kpis["fuel_l"]         += total_fuel
        kpis["co2_kg"]         += co2
        kpis["cost_tl"]        += cost
        kpis["dispatch_count"] += 1

    # endregion

    # =========================================================================
    # region: Kamyon İlerlemesi (_advance_trucks, _step_truck)
    # Her tick'te tüm aktif kamyonların konumunu ve durumunu günceller.
    # en_route → servicing → returning → done geçişlerini yönetir.
    # Tamamlanan fixed kamyon sayısı kadar yeni fixed rota devreye alınır.
    # =========================================================================

    @staticmethod
    def _active_stop_bin_ids(truck_list: list) -> set[str]:
        """Aktif kamyonların henüz servise almadığı durakların bin_id kümesi."""
        return {
            stop.bin_id
            for truck in truck_list
            for stop in truck.stops[truck.current_stop_idx:]
        }

    def _advance_trucks(self) -> None:
        s = self._sim_s
        for truck_list, world_bins, world_name, is_fixed in (
            (self.algo_trucks,  self.algo_bins,  "algo",  False),
            (self.fixed_trucks, self.fixed_bins, "fixed", True),
        ):
            for truck in truck_list:
                if truck.status != "done":
                    self._step_truck(truck, s, world_bins, world_name)

            done_count = sum(1 for t in truck_list if t.status == "done")
            truck_list[:] = [t for t in truck_list if t.status != "done"]

            # Sabit rota (yalnızca lo_dcs): tamamlanan her kamyon için sıradaki
            # rotayı devreye al. aco/hho zaten dinamik dispatch job'larından
            # (_job_dispatch_fixed_aco_dynamic / _hho_preopt+_hho_reopt) yeni
            # kamyon alır; cursor mantığı onlara uygulanmaz.
            if is_fixed and done_count > 0 and self.fixed_algorithm == "lo_dcs":
                for _ in range(done_count):
                    self._dispatch_next_fixed_route()

    def _step_truck(self, t: TruckRoute, s: float, world_bins: dict, world_name: str) -> None:
        if t.status == "en_route":
            if s >= t.leg_end_sim_s:
                t.lat    = t.to_lat
                t.lon    = t.to_lon
                stop     = t.stops[t.current_stop_idx]
                t.at_bin = stop.bin_id
                t.to_bin = None
                t.status = "servicing"
                t.service_end_sim_s = t.leg_end_sim_s + SERVICE_SIM_MIN * 60
                t.progress = 1.0
                if stop.bin_id in world_bins:
                    b        = world_bins[stop.bin_id]
                    bin_load = (b.fill_pct / 100.0) * BIN_VOLUME_FRACTION
                    t.capacity_used = min(TRUCK_CAPACITY, t.capacity_used + bin_load)
                    self._append_history("EMPTIED", b, world_name)
                    kpis = self.algo_kpis if world_name == "algo" else self.fixed_kpis
                    kpis["bins_collected"] += 1
                    kpis["load_collected"] += b.fill_pct   # toplanan gerçek yük (%cinsinden)
                    b.empty(self._sim_s)
            else:
                seg        = max(1.0, t.leg_end_sim_s - t.leg_start_sim_s)
                t.progress = max(0.0, min(1.0, (s - t.leg_start_sim_s) / seg))
                t.lat      = t.from_lat + (t.to_lat - t.from_lat) * t.progress
                t.lon      = t.from_lon + (t.to_lon - t.from_lon) * t.progress
                t.to_bin   = t.stops[t.current_stop_idx].bin_id

        elif t.status == "servicing":
            if s >= t.service_end_sim_s:
                t.current_stop_idx += 1
                t.at_bin = None
                if t.current_stop_idx < len(t.stops):
                    nxt    = t.stops[t.current_stop_idx]
                    dist   = _haversine_km(t.lat, t.lon, nxt.lat, nxt.lon)
                    t.from_lat        = t.lat
                    t.from_lon        = t.lon
                    t.to_lat          = nxt.lat
                    t.to_lon          = nxt.lon
                    t.leg_start_sim_s = s
                    t.leg_end_sim_s   = s + (dist / TRUCK_SPEED_KMH) * 3600
                    t.to_bin          = nxt.bin_id
                    t.status          = "en_route"
                    t.progress        = 0.0
                else:
                    dist   = _haversine_km(t.lat, t.lon, self.depot_lat, self.depot_lon)
                    t.from_lat        = t.lat
                    t.from_lon        = t.lon
                    t.to_lat          = self.depot_lat
                    t.to_lon          = self.depot_lon
                    t.leg_start_sim_s = s
                    t.leg_end_sim_s   = s + (dist / TRUCK_SPEED_KMH) * 3600
                    t.to_bin          = None
                    t.status          = "returning"
                    t.progress        = 0.0

        elif t.status == "returning":
            if s >= t.leg_end_sim_s:
                t.lat    = self.depot_lat
                t.lon    = self.depot_lon
                t.status = "done"
            else:
                seg        = max(1.0, t.leg_end_sim_s - t.leg_start_sim_s)
                t.progress = max(0.0, min(1.0, (s - t.leg_start_sim_s) / seg))
                t.lat      = t.from_lat + (t.to_lat - t.from_lat) * t.progress
                t.lon      = t.from_lon + (t.to_lon - t.from_lon) * t.progress

    # endregion

    # =========================================================================
    # region: Event Job (Phase 1)
    # EventManager'ı her tick'te çalıştırır.
    # Yeni event oluştuğunda anomali loguna da kaydeder (canlı panoda görünür).
    # =========================================================================

    def _job_events(self) -> None:
        """Event manager'ı tick'le; yeni event varsa anomali loguna da yaz."""
        new_event = self._event_manager.tick(self._sim_s)
        if new_event:
            self.recent_anomalies.append({
                "bin_id":       "CITY",
                "event_type":   f"EVENT_{new_event.event_type.upper()}",
                "virtual_time": self.virtual_clock.isoformat(),
                "details":      new_event.description,
            })
            if len(self.recent_anomalies) > 50:
                self.recent_anomalies.pop(0)

    # endregion

    # =========================================================================
    # region: Fill History Logger (_append_history)
    # EMPTIED ve OVERFLOW olaylarını fill_history listesine ekler.
    # Bellek sınırını (MAX_FILL_HISTORY) aşarsa eski kayıtları keser.
    # Yalnızca algo dünyasından gelen olaylar predictor'a da iletilir.
    # =========================================================================

    def _append_history(self, event: str, b: BinState, world: str) -> None:
        self.fill_history.append({
            "sim_time":       self.virtual_clock.isoformat(),
            "world":          world,
            "bin_id":         b.bin_id,
            "event":          event,
            "fill_pct":       round(b.fill_pct, 1),
            "fill_label":     b.fill_label,
            "distance_label": b.distance_label,
            "fill_rate":      b.fill_rate,
        })
        if len(self.fill_history) > MAX_FILL_HISTORY:
            self.fill_history = self.fill_history[-MAX_FILL_HISTORY:]
        # Predictor'ı sadece algo dünyasından besle
        if world == "algo":
            self._predictor.record_event(event, b.bin_id, self._sim_s)

    # endregion

    # =========================================================================
    # region: Anomaly Job ve Healing (_job_anomaly, _heal_anomalies)
    # Rastgele aralıklarla 4 farklı anomali türü üretir ve bin state'lerine yazar.
    # _heal_anomalies: anomali süresi dolan bin'leri normal duruma döndürür.
    # _log_anomaly_db: anomalileri isteğe bağlı olarak veritabanına da yazar.
    # =========================================================================

    ANOMALY_TYPES      = ["OVERFLOW_RISK", "FILL_ANOMALY", "SENSOR_FIXED_VALUE_ERROR", "BIN_OFFLINE"]
    OFFLINE_DURATION_S = (5 * 60, 15 * 60)

    def _job_anomaly(self) -> None:
        if self._sim_s < self._next_anomaly_s:
            return
        self._next_anomaly_s = self._sim_s + self._rand_anomaly_s()

        bin_ids = list(self.algo_bins.keys())
        if not bin_ids:
            return

        bin_id    = random.choice(bin_ids)
        atype     = random.choice(self.ANOMALY_TYPES)
        algo_bin  = self.algo_bins.get(bin_id)
        fixed_bin = self.fixed_bins.get(bin_id)

        if atype == "OVERFLOW_RISK":
            # OVERFLOW_RISK anomalisini rastgele sadece BİR dünyaya uygula
            target = random.choice(["algo", "fixed"])
            b      = algo_bin if target == "algo" else fixed_bin
            kpis   = self.algo_kpis if target == "algo" else self.fixed_kpis
            if b:
                b.fill_pct = 95.0
                b.status   = "CRITICAL_FULL"
                kpis["overflow_events"] += 1

        elif atype == "FILL_ANOMALY":
            for b in (algo_bin, fixed_bin):
                if b:
                    b.fill_pct = 0.0
                    b.refresh_status()

        elif atype in ("SENSOR_FIXED_VALUE_ERROR", "BIN_OFFLINE"):
            end_s      = self._sim_s + random.uniform(*self.OFFLINE_DURATION_S)
            new_status = "SENSOR_ERROR" if atype == "SENSOR_FIXED_VALUE_ERROR" else "OFFLINE"
            for b in (algo_bin, fixed_bin):
                if b:
                    b.status            = new_status
                    b.is_anomaly        = True
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

        self._log_anomaly_db(bin_id, atype, {"virtual_time": self.virtual_clock.isoformat()})

    def _heal_anomalies(self) -> None:
        for world in (self.algo_bins, self.fixed_bins):
            for b in world.values():
                if b.is_anomaly and 0 < b.anomaly_end_sim_s <= self._sim_s:
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
            pass

    # endregion

    # =========================================================================
    # region: Snapshot Metodları (state_snapshot, kpis_snapshot)
    # Motor anlık durumunu ve KPI özetini dışarıya (API / WebSocket) sunar.
    # state_snapshot: tüm bin, truck ve event verilerini birleştirerek döndürür.
    # kpis_snapshot: algo vs fixed karşılaştırmasını ve tasarruf özetini verir.
    # =========================================================================

    def state_snapshot(self) -> dict:
        return {
            "virtual_clock":    self.virtual_clock.isoformat(),
            "is_running":       self.is_running,
            "speed_multiplier": self.speed_multiplier,
            "depot_lat":        self.depot_lat,
            "depot_lon":        self.depot_lon,
            "fixed_algorithm":  self.fixed_algorithm,
            "algo_bins":        [_bin_to_dict(b, self._sim_s, self._sim_epoch)
                                 for b in self.algo_bins.values()],
            "fixed_bins":       [_bin_to_dict(b, self._sim_s, self._sim_epoch)
                                 for b in self.fixed_bins.values()],
            "algo_trucks":      [_truck_to_dict(t, self.depot_lat, self.depot_lon)
                                 for t in self.algo_trucks],
            "fixed_trucks":     [_truck_to_dict(t, self.depot_lat, self.depot_lon)
                                 for t in self.fixed_trucks],
            # Phase 1 — frontend'de aktif eventleri göster
            "active_events":    [
                {
                    "event_id":    e.event_id,
                    "event_type":  e.event_type,
                    "description": e.description,
                    "multiplier":  e.multiplier,
                }
                for e in self._event_manager.active(self._sim_s)
            ],
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
                "co2_kg":        round(f["co2_kg"]  - a["co2_kg"],  1),
                "fuel_l":        round(f["fuel_l"]  - a["fuel_l"],  1),
                "cost_tl":       round(f["cost_tl"] - a["cost_tl"], 1),
                "overflow_diff": f["overflow_count"] - a["overflow_count"],
            },
        }

    # endregion

# endregion  (SimulationEngine sınıfı sonu)


# =============================================================================
# region: Singleton
# Modül import edildiğinde tek bir SimulationEngine örneği oluşturulur.
# =============================================================================

engine = SimulationEngine()

# endregion