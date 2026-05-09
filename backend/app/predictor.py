"""
FillPredictor — veri tabanlı dolum tahmini + coğrafi zone yönetimi.

Öğrenme kaynağı: SimulationEngine fill_history logları (sadece "algo" dünyası)
  EMPTIED → başlangıç zaman damgasını kaydet
  OVERFLOW → cycle = şimdi − son_EMPTIED; rolling ortalama ile rate güncelle

Başlangıçta (veri yokken) fallback olarak her bin'in konfigüre edilmiş
fill_rate değeri kullanılır. Simülasyon ilerledikçe gerçek gözleme geçer.

Public API:
  predictor.assign_zones(bins)                      → load_bins() sonrası bir kez
  predictor.record_event(event, bin_id, sim_s)      → her algo log olayında
  predictor.zone_ready_bins(available, lookahead_h) → dispatch tick'inde
  predictor.predicted_etf_h(bin_id, fill_pct, fallback) → ETF tahmini
  predictor.reset()                                 → simülasyon sıfırlandığında
"""
from __future__ import annotations

import math
import random
from collections import defaultdict

# ── Sabitler ──────────────────────────────────────────────────────────────────

N_ZONES           = 12    # K-means zone sayısı (mikro-zone: daha küçük, daha yoğun)
KMEANS_ITERATIONS = 25    # Lloyd iterasyon sayısı
MAX_CYCLES        = 8     # bin başına rolling window büyüklüğü
LOOKAHEAD_H       = 7.0   # sim saat — bu süre içinde dolacak bin'ler "zone-ready"
MIN_ZONE_BINS     = 6     # zone dispatch tetiklemek için minimum bin sayısı


# ── Yardımcı ──────────────────────────────────────────────────────────────────

def _geo_dist(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(max(0.0, a)))


# ══════════════════════════════════════════════════════════════════════════════
# FillPredictor
# ══════════════════════════════════════════════════════════════════════════════

class FillPredictor:
    """
    İki sorumluluğu var:
      1. Coğrafi zone ataması (K-means, startup'ta bir kez)
      2. Fill history loglarından dolum süresini öğrenme ve ETF tahmini
    """

    def __init__(self) -> None:
        self._cycles:       dict[str, list[float]]   = {}           # bin_id → dolum süreleri (sim-s)
        self._last_emptied: dict[str, float]          = {}           # bin_id → son EMPTIED sim_s
        self._bin_zone:     dict[str, int]            = {}           # bin_id → zone_id
        self._zone_bins:    dict[int, list[str]]      = defaultdict(list)
        self._centroids:    list[tuple[float, float]] = []

    # ── Zone ataması ───────────────────────────────────────────────────────

    def assign_zones(self, bins: list, n_zones: int = N_ZONES) -> None:
        """
        K-means++ ile coğrafi zone ataması.
        load_bins() çağrısından hemen sonra bir kez çalıştırılır.
        Bin konumları değişmediği için reset()'te tekrar çağırmaya gerek yok.
        """
        if not bins:
            return

        points: list[tuple[str, float, float]] = [(b.bin_id, b.lat, b.lon) for b in bins]
        n = min(n_zones, len(points))

        # K-means++ başlangıç centroid'leri
        centroids: list[tuple[float, float]] = [random.choice(points)[1:]]
        while len(centroids) < n:
            dists = [
                min(_geo_dist(p[1], p[2], c[0], c[1]) for c in centroids)
                for p in points
            ]
            total = sum(dists) or 1.0
            r = random.random() * total
            acc = 0.0
            for p, d in zip(points, dists):
                acc += d
                if acc >= r:
                    centroids.append((p[1], p[2]))
                    break

        # Lloyd iterasyonları
        for _ in range(KMEANS_ITERATIONS):
            clusters: dict[int, list[tuple[str, float, float]]] = defaultdict(list)
            for bid, lat, lon in points:
                nearest = min(
                    range(len(centroids)),
                    key=lambda i: _geo_dist(lat, lon, centroids[i][0], centroids[i][1]),
                )
                clusters[nearest].append((bid, lat, lon))

            new_centroids: list[tuple[float, float]] = []
            for i in range(len(centroids)):
                cluster = clusters.get(i, [])
                if cluster:
                    new_centroids.append((
                        sum(p[1] for p in cluster) / len(cluster),
                        sum(p[2] for p in cluster) / len(cluster),
                    ))
                else:
                    new_centroids.append(centroids[i])
            centroids = new_centroids

        # Final atama
        self._centroids = centroids
        self._bin_zone.clear()
        self._zone_bins.clear()
        for bid, lat, lon in points:
            zone = min(
                range(len(centroids)),
                key=lambda i: _geo_dist(lat, lon, centroids[i][0], centroids[i][1]),
            )
            self._bin_zone[bid] = zone
            self._zone_bins[zone].append(bid)

    # ── Event besleme ──────────────────────────────────────────────────────

    def record_event(self, event: str, bin_id: str, sim_s: float) -> None:
        """
        fill_history log olayını predictor'a ilet.
        Yalnızca "algo" dünyası için çağrılmalıdır.

        EMPTIED → son boşaltma zamanını kaydet
        OVERFLOW → o cycle'ın süresini rolling window'a ekle
        """
        if event == "EMPTIED":
            self._last_emptied[bin_id] = sim_s
        elif event == "OVERFLOW":
            last = self._last_emptied.get(bin_id)
            if last is not None and sim_s > last:
                cycle_s = sim_s - last
                cycles  = self._cycles.setdefault(bin_id, [])
                cycles.append(cycle_s)
                if len(cycles) > MAX_CYCLES:
                    cycles.pop(0)

    # ── Tahmin ─────────────────────────────────────────────────────────────

    def predicted_fill_rate_h(self, bin_id: str, fallback_rate: float) -> float:
        """
        Tahmin edilen dolum hızı (%/sim-saat).
        Gözlem sayısı < 2 ise konfigüre edilmiş fallback_rate döner.
        """
        cycles = self._cycles.get(bin_id, [])
        if len(cycles) < 2:
            return fallback_rate
        avg_s = sum(cycles) / len(cycles)
        return 100.0 / (avg_s / 3600.0)

    def predicted_etf_h(
        self,
        bin_id: str,
        fill_pct: float,
        fallback_rate: float,
    ) -> float:
        """Taşmaya kalan tahmin edilen sim-saat."""
        rate = self.predicted_fill_rate_h(bin_id, fallback_rate)
        if rate <= 0:
            return float("inf")
        return max(0.0, (100.0 - fill_pct) / rate)

    def has_learned(self, bin_id: str) -> bool:
        """Bu bin için en az 2 gözlem var mı?"""
        return len(self._cycles.get(bin_id, [])) >= 2

    # ── Zone sorgusu ───────────────────────────────────────────────────────

    def zone_ready_bins(
        self,
        available: dict,
        lookahead_h: float = LOOKAHEAD_H,
    ) -> dict[int, list]:
        """
        lookahead_h penceresi içinde dolacağı tahmin edilen bin'leri
        zone bazında gruplandırarak döndür.

        Args:
          available: {bin_id: BinState} — claimed ve extended olmayanlar
          lookahead_h: kaç sim saat ilerisi için tahmin yapılsın

        Returns:
          {zone_id: [BinState, ...]} — yalnızca MIN_ZONE_BINS üzeri zone'lar
        """
        zone_ready: dict[int, list] = defaultdict(list)

        for bin_id, b in available.items():
            if b.is_anomaly or b.fill_pct <= 0:
                continue
            zone = self._bin_zone.get(bin_id)
            if zone is None:
                continue
            etf = self.predicted_etf_h(bin_id, b.fill_pct, b.fill_rate)
            if etf <= lookahead_h:
                zone_ready[zone].append(b)

        return {z: bins for z, bins in zone_ready.items() if len(bins) >= MIN_ZONE_BINS}

    def urgent_zone_bins(
        self,
        available: dict,
        etf_threshold_h: float,
        min_bins: int,
    ) -> dict[int, list]:
        """
        ETF ≤ etf_threshold_h olan bin'leri zone bazında grupla.
        min_bins eşiğini geçen zone'ları döndür.

        Normal zone_ready_bins'ten farkı: threshold ve min_bins parametrik;
        taşma önleme için çok daha kısa ETF penceresiyle çağrılır.
        """
        zone_urgent: dict[int, list] = defaultdict(list)

        for bin_id, b in available.items():
            if b.is_anomaly:
                continue
            zone = self._bin_zone.get(bin_id)
            if zone is None:
                continue
            etf = self.predicted_etf_h(bin_id, b.fill_pct, b.fill_rate)
            if etf <= etf_threshold_h:
                zone_urgent[zone].append(b)

        return {z: bins for z, bins in zone_urgent.items() if len(bins) >= min_bins}

    def coverage_zone_bins(
        self,
        available: dict,
        zone_id: int,
        min_fill: float,
    ) -> list:
        """
        Belirtilen zone'daki min_fill üzerindeki bin'leri döndür.
        Coverage rotation tarafından çağrılır: doluluktan bağımsız
        düzenli ziyaret sırasında hangi bin'lerin toplanacağını belirler.
        """
        return [
            b for bid, b in available.items()
            if not b.is_anomaly
            and b.fill_pct >= min_fill
            and self._bin_zone.get(bid) == zone_id
        ]

    def adaptive_coverage_interval_s(
        self,
        zone_id: int,
        available: dict,
        base_interval_s: float,
    ) -> float:
        """
        Zone'daki bin'lerin medyan ETF'ine göre coverage interval'ı ayarla.

        Hızlı dolan zone → kısa interval (sık ziyaret).
        Yavaş dolan zone → uzun interval (seyrek ziyaret, yakıt tasarrufu).
        Clamp: [base/4 .. base*3]
        """
        zone_bin_ids = self._zone_bins.get(zone_id, [])
        etfs: list[float] = []
        for bid in zone_bin_ids:
            b = available.get(bid)
            if b is None or b.is_anomaly or b.fill_pct <= 0:
                continue
            etf = self.predicted_etf_h(bid, b.fill_pct, b.fill_rate)
            if etf < 1e9:
                etfs.append(etf)

        if not etfs:
            return base_interval_s

        etfs.sort()
        median_etf_h = etfs[len(etfs) // 2]
        base_h       = base_interval_s / 3600.0
        ratio        = max(0.25, min(3.0, median_etf_h / base_h))
        return base_interval_s * ratio

    def zone_of(self, bin_id: str) -> int | None:
        return self._bin_zone.get(bin_id)

    def n_zones(self) -> int:
        return len(self._zone_bins)

    def centroid_of(self, zone_id: int) -> tuple[float, float] | None:
        if zone_id < len(self._centroids):
            return self._centroids[zone_id]
        return None

    # ── Sıfırlama ──────────────────────────────────────────────────────────

    def reset(self) -> None:
        """
        Öğrenilen dolum verilerini sil; zone atamaları korunur
        (bin konumları değişmez, K-means'i tekrar çalıştırmak gerekmez).
        """
        self._cycles.clear()
        self._last_emptied.clear()
