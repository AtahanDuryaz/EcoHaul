"""
DPET - Dynamic Priority & Efficient Truck dispatch algorithm.

Hedefler:
  1. Taşmayı minimuma indir  → ETF (taşmaya kalan süre) bazlı önceden seçim
  2. Km'yi minimuma indir    → NN başlangıcı + tam 2-opt (TSP kalitesi)
  3. Verimli sefer           → km başına yetersiz bin varsa kamyon çıkmasın
  4. Trafik farkındalığı     → yoğun saatlerde sadece acil bin seç
  5. Hacimsel kapasite       → doluluk oranına göre kamyon kapasitesi tüketimi

Katmanlar:
  TrafficModel    : saat bazlı trafik skoru (0–1)
  BinScorer       : doluluk + ETF + yakınlık + trafik (4 bileşen skoru)
  BinSelector     : ETF eşiği ile erken yakalama; acil override; rush filtresi
  RouteBuilder    : NN heuristik → kapasite kırpma → tam 2-opt
  RouteEfficiency : dispatch öncesi bin/km oranı kontrolü
  Dispatcher      : filo durumuna göre kaç kamyon çıkacağına karar ver
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

# ── Paylaşılan stop tipi ───────────────────────────────────────────────────────

@dataclass
class Stop:
    bin_id: str
    lat: float
    lon: float


# ── Duck-typed bin arayüzü ────────────────────────────────────────────────────

class _BinLike(Protocol):
    bin_id: str
    lat: float
    lon: float
    fill_pct: float
    fill_rate: float     # %/sim-saat — ETF hesabı için gerekli
    distance_label: int
    is_anomaly: bool


# ══════════════════════════════════════════════════════════════════════════════
# Hacimsel kapasite sabitleri (simulation_engine tarafından da kullanılır)
# ══════════════════════════════════════════════════════════════════════════════

TRUCK_CAPACITY      = 1.0    # kamyon toplam kapasitesi (normalize)
BIN_VOLUME_FRACTION = 0.05   # %100 dolu bir bin kamyonun %5'ini doldurur
FUEL_WEIGHT_FACTOR  = 0.8    # tam dolu kamyon boş kamyona göre %80 daha fazla yakıt yakar


# ── Coğrafi yardımcı ──────────────────────────────────────────────────────────

def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(max(0.0, a)))


# ══════════════════════════════════════════════════════════════════════════════
# KATMAN 1 — TrafficModel
# ══════════════════════════════════════════════════════════════════════════════

_RUSH_HOURS = frozenset({7, 8, 9, 17, 18, 19})
_PEAK_HOURS = frozenset({6, 10, 16, 20})


def traffic_score(hour: int) -> float:
    """0.0 = boş yol (gece)  →  1.0 = tam tıkanıklık"""
    if hour in _RUSH_HOURS:
        return 0.80
    if hour in _PEAK_HOURS:
        return 0.50
    return 0.20


# ══════════════════════════════════════════════════════════════════════════════
# KATMAN 2 — BinScorer  (4 bileşen: doluluk + ETF + yakınlık + trafik)
# ══════════════════════════════════════════════════════════════════════════════

_W_FILL      = 0.40   # anlık doluluk baskısı
_W_ETF       = 0.35   # taşmaya kalan süre — erken yakalamayı ödüllendirir
_W_PROXIMITY = 0.05   # yakın bin → rota verimli (seçimde küçük etki)
_W_TRAFFIC   = 0.12   # az trafikte gönder
_W_DENSITY   = 0.08   # yakın çevredeki yüksek-doluluklu bin yoğunluğu

_ETF_HORIZON        = 8.0    # 8 sim saatin altındaki ETF skora katkı yapar
_DENSITY_RADIUS_KM  = 1.0    # yoğunluk hesabı için yarıçap (km)
_DENSITY_MAX_BINS   = 10     # normalizasyon: 10+ bin → yoğunluk skoru = 1.0
_DENSITY_MIN_FILL   = 65.0   # yoğunluk sayımına dahil edilecek minimum doluluk


def _etf_hours(fill_pct: float, fill_rate: float) -> float:
    """Mevcut doluluk ve hıza göre taşmaya kalan sim saat. fill_rate=0 → ∞"""
    if fill_rate <= 0:
        return float("inf")
    return max(0.0, (100.0 - fill_pct) / fill_rate)


def _count_nearby_bins(
    lat: float, lon: float, bins, radius_km: float, min_fill: float
) -> int:
    """Belirtilen yarıçap içinde min_fill üzerindeki bin sayısı (kendisi hariç)."""
    count = 0
    for b in bins:
        if b.is_anomaly or b.fill_pct < min_fill:
            continue
        if _km(lat, lon, b.lat, b.lon) < 1e-6:
            continue   # aynı bin
        if _km(lat, lon, b.lat, b.lon) <= radius_km:
            count += 1
    return count


def score_bin(
    fill_pct: float,
    fill_rate: float,
    distance_label: int,
    traffic: float,
    density_norm: float = 0.0,
) -> float:
    """
    Öncelik skoru: [0.0, 1.0]

      fill_urgency : (fill_pct/100)² — kritik bin'ler çok daha yüksek skor
      etf_urgency  : taşmaya kalan süre azaldıkça artar (ETF_HORIZON'dan 0'a)
      proximity    : dist 1→1.0, 2→0.5, 3→0.0
      traffic_ok   : trafik az = iyi zaman
      density_norm : yakın çevredeki yüksek-dolu bin yoğunluğu [0,1]
    """
    fill_urgency = (fill_pct / 100.0) ** 2
    etf          = _etf_hours(fill_pct, fill_rate)
    etf_urgency  = max(0.0, 1.0 - etf / _ETF_HORIZON)   # 8h+ → 0, 0h → 1
    proximity    = 1.0 - (distance_label - 1) / 2.0
    traffic_ok   = 1.0 - traffic

    return (_W_FILL * fill_urgency
            + _W_ETF * etf_urgency
            + _W_PROXIMITY * proximity
            + _W_TRAFFIC * traffic_ok
            + _W_DENSITY * density_norm)


# ══════════════════════════════════════════════════════════════════════════════
# KATMAN 3 — BinSelector
# ══════════════════════════════════════════════════════════════════════════════

_MIN_FILL_NORMAL = 65.0   # normal saatlerde %65+ dolu bin adaya girer
_MIN_FILL_RUSH   = 85.0   # rush saatlerde sadece %85+
_RUSH_THR        = 0.70

ETF_LEAD_TIME    = 3.0    # taşmaya ≤3 sim saat kalan bin → fill_pct eşiğini atla
_EMERGENCY_FILL  = 88.0   # %88+ → MIN_DISPATCH şartını bypass et

MIN_DISPATCH = 8           # en az 8 bin seçilemezse (ve acil yoksa) dispatch yapma


@dataclass
class _ScoredStop:
    stop: Stop
    score: float
    dist_from_depot: float
    fill_pct: float
    etf_h: float            # taşmaya kalan sim saat


def select_bins(
    bins: list[_BinLike],
    traffic: float,
    depot_lat: float,
    depot_lon: float,
    max_stops: int,
) -> list[_ScoredStop]:
    """
    Bin seçim mantığı:
      1. Acil (%95+)           → her zaman dahil et
      2. ETF ≤ ETF_LEAD_TIME   → fill_pct eşiğine bakmaksızın dahil et (erken yakalama)
      3. fill_pct ≥ min_fill   → normal eşikle dahil et
      4. Skor sırasına koy, en iyi max_stops bin'i döndür
    """
    min_fill = _MIN_FILL_RUSH if traffic > _RUSH_THR else _MIN_FILL_NORMAL

    # İlk geçiş: uygun bin'leri filtrele
    eligible: list[tuple] = []
    for b in bins:
        if b.is_anomaly:
            continue
        etf = _etf_hours(b.fill_pct, b.fill_rate)
        is_emergency      = b.fill_pct >= _EMERGENCY_FILL
        is_etf_urgent     = etf <= ETF_LEAD_TIME
        is_above_threshold = b.fill_pct >= min_fill
        if not (is_emergency or is_etf_urgent or is_above_threshold):
            continue
        eligible.append((b, etf))

    # İkinci geçiş: yoğunluk dahil skor hesapla (tüm bins listesi kullanılır)
    result: list[_ScoredStop] = []
    for b, etf in eligible:
        nearby       = _count_nearby_bins(b.lat, b.lon, bins, _DENSITY_RADIUS_KM, _DENSITY_MIN_FILL)
        density_norm = min(1.0, nearby / _DENSITY_MAX_BINS)
        s = score_bin(b.fill_pct, b.fill_rate, b.distance_label, traffic, density_norm)
        d = _km(depot_lat, depot_lon, b.lat, b.lon)
        result.append(_ScoredStop(Stop(b.bin_id, b.lat, b.lon), s, d, b.fill_pct, etf))

    result.sort(key=lambda x: x.score, reverse=True)
    return result[:max_stops]


# ══════════════════════════════════════════════════════════════════════════════
# KATMAN 4 — RouteBuilder  (NN + tam 2-opt)
# ══════════════════════════════════════════════════════════════════════════════

def _nn_route(scored: list[_ScoredStop], depot_lat: float, depot_lon: float) -> list[_ScoredStop]:
    """
    Nearest-Neighbor sıralama: depot'tan başla, her adımda en yakın bin'e git.
    Kapasite kırpmasından önce uygulanır; sıralamayla hangi binlerin önce
    yüklendiği kapasiteyi aşan binlerin doğal olarak sona kalmasını sağlar.
    """
    remaining = list(scored)
    route: list[_ScoredStop] = []
    cur_lat, cur_lon = depot_lat, depot_lon

    while remaining:
        closest = min(remaining, key=lambda ss: _km(cur_lat, cur_lon, ss.stop.lat, ss.stop.lon))
        route.append(closest)
        cur_lat, cur_lon = closest.stop.lat, closest.stop.lon
        remaining.remove(closest)

    return route


def _trim_by_capacity(nn_ordered: list[_ScoredStop]) -> list[_ScoredStop]:
    """
    NN sıralamasına göre kamyon kapasitesi dolana kadar bin ekle.
    Kapasite aşıldığı noktada dur; kalan bin'ler bir sonraki kamyona kalır.
    """
    result: list[_ScoredStop] = []
    used = 0.0
    for ss in nn_ordered:
        load = (ss.fill_pct / 100.0) * BIN_VOLUME_FRACTION
        if used + load > TRUCK_CAPACITY + 1e-9:
            break
        result.append(ss)
        used += load
    return result


def build_route(
    scored: list[_ScoredStop],
    depot_lat: float,
    depot_lon: float,
) -> list[Stop]:
    """
    NN sıralama → kapasite kırpma → tam 2-opt.
    Kapasite kırpması gerçekçi yük sınırını uygular;
    2-opt kırpılmış set üzerinde TSP kalitesi rota üretir.
    """
    if not scored:
        return []
    nn_ordered = _nn_route(scored, depot_lat, depot_lon)
    trimmed    = _trim_by_capacity(nn_ordered)
    stops      = [ss.stop for ss in trimmed]
    return _full_2opt(stops, depot_lat, depot_lon)


def _route_dist(stops: list[Stop], dlat: float, dlon: float) -> float:
    if not stops:
        return 0.0
    d = _km(dlat, dlon, stops[0].lat, stops[0].lon)
    for i in range(len(stops) - 1):
        d += _km(stops[i].lat, stops[i].lon, stops[i + 1].lat, stops[i + 1].lon)
    d += _km(stops[-1].lat, stops[-1].lon, dlat, dlon)
    return d


def _fuel_aware_dist(stops: list[Stop], dlat: float, dlon: float) -> float:
    """
    Ağırlık-duyarlı yakıt maliyeti (normalize edilmiş).

    Kamyon her durakta dolunca ağırlaşır; bu ağırlık sonraki bacakların
    yakıt maliyetini artırır. 2-opt bu maliyeti minimize ederek erken
    durakları hafif tutmaya çalışır — hafif yük = uzun mesafede az yakıt.

    Formül: cost_i = dist_i × (1 + FUEL_WEIGHT_FACTOR × i/n)
    """
    n = len(stops)
    if n == 0:
        return 0.0
    cost = _km(dlat, dlon, stops[0].lat, stops[0].lon)   # ilk bacak — boş kamyon
    for i in range(n - 1):
        dist     = _km(stops[i].lat, stops[i].lon, stops[i + 1].lat, stops[i + 1].lon)
        w_factor = (i + 1) / n                            # 0 → 1 arası artar
        cost    += dist * (1.0 + FUEL_WEIGHT_FACTOR * w_factor)
    # Dönüş bacağı — kamyon tamamen dolu
    cost += _km(stops[-1].lat, stops[-1].lon, dlat, dlon) * (1.0 + FUEL_WEIGHT_FACTOR)
    return cost


def _full_2opt(stops: list[Stop], dlat: float, dlon: float) -> list[Stop]:
    """
    Tam 2-opt: ağırlık-duyarlı yakıt maliyetini minimize eder.

    Standart km minimizasyonu yerine _fuel_aware_dist kullanılır.
    Bu sayede algo yolu kısaltırken aynı zamanda hafif yükle uzun,
    ağır yükle kısa bacakları tercih eder.
    """
    n = len(stops)
    best     = list(stops)
    best_len = _fuel_aware_dist(best, dlat, dlon)
    improved = True
    while improved:
        improved = False
        for i in range(n - 1):
            for j in range(i + 2, n):
                cand = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                clen = _fuel_aware_dist(cand, dlat, dlon)
                if clen < best_len - 1e-6:
                    best, best_len, improved = cand, clen, True
    return best


# ══════════════════════════════════════════════════════════════════════════════
# KATMAN 5 — RouteEfficiency
# ══════════════════════════════════════════════════════════════════════════════

_MIN_ROUTE_EFFICIENCY = 0.20   # minimum bin/km oranı


def route_efficiency(stops: list[Stop], depot_lat: float, depot_lon: float) -> float:
    """Bin sayısı / toplam km. Düşükse bu rota boşa gidiş."""
    dist = _route_dist(stops, depot_lat, depot_lon)
    if dist < 1e-6:
        return float("inf")
    return len(stops) / dist


def _chunk_is_urgent(chunk: list[_ScoredStop]) -> bool:
    """Grupta acil (%95+) veya ETF kritik bin var mı?"""
    return any(ss.fill_pct >= _EMERGENCY_FILL or ss.etf_h <= ETF_LEAD_TIME for ss in chunk)


# ══════════════════════════════════════════════════════════════════════════════
# KATMAN 6 — Dispatcher
# ══════════════════════════════════════════════════════════════════════════════

def dpet_dispatch(
    bins: list[_BinLike],
    active_truck_count: int,
    hour: int,
    depot_lat: float,
    depot_lon: float,
    max_fleet: int,
    max_stops: int,
) -> list[list[Stop]]:
    """
    Ana dispatch fonksiyonu.

    Karar akışı:
      1. Boş filo slotu yoksa dur
      2. ETF + doluluk bazlı bin seçimi yap
      3. Acil bin yoksa ve toplam < MIN_DISPATCH → toplu rota için bekle
      4. max_stops'luk gruplara böl → NN + tam 2-opt rota kur
      5. Verimsiz + acilsiz rota → atla
      6. Kalan rotaları döndür
    """
    available_slots = max_fleet - active_truck_count
    if available_slots <= 0:
        return []

    traffic = traffic_score(hour)

    selected = select_bins(
        bins, traffic, depot_lat, depot_lon,
        max_stops=max_stops * available_slots,
    )

    has_any_urgent = any(ss.fill_pct >= _EMERGENCY_FILL or ss.etf_h <= ETF_LEAD_TIME
                         for ss in selected)

    if len(selected) < MIN_DISPATCH and not has_any_urgent:
        return []

    routes: list[list[Stop]] = []
    for i in range(0, len(selected), max_stops):
        chunk = selected[i:i + max_stops]

        if len(chunk) < MIN_DISPATCH and not _chunk_is_urgent(chunk):
            break

        route = build_route(chunk, depot_lat, depot_lon)
        if not route:
            break

        eff = route_efficiency(route, depot_lat, depot_lon)
        if eff < _MIN_ROUTE_EFFICIENCY and not _chunk_is_urgent(chunk):
            continue

        routes.append(route)
        if len(routes) >= available_slots:
            break

    return routes
