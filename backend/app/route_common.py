"""
Fixed-route dünyasının rota algoritmaları arasında paylaşılan yardımcılar.

Üç algoritma da aynı iskeleti kullanır: K-Means ile kapasite büyüklüğünde
kümeleme (Kim et al. 2023'ün "clustering-based decomposition" adımıyla aynı
mantık, LO-DCS ve Improved HHO makalelerinde de aynı fikir tekrarlanır),
ardından her küme için kendi metasezgiselini bağımsız çalıştırma.

Bu modül geometriyi (haversine, rota uzunluğu) ve kümelemeyi tek yerde tutar;
lo_dcs.py / aco_route.py / hho_route.py sadece küme-içi arama stratejisini
farklılaştırır.
"""
from __future__ import annotations

import math
import random
from typing import Protocol


class BinLike(Protocol):
    bin_id: str
    lat: float
    lon: float


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R    = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a    = (math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
            * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(max(0.0, a)))


def route_length_km(order: list[BinLike], depot_lat: float, depot_lon: float) -> float:
    """Depot → duraklar → depot toplam mesafesi (km)."""
    if not order:
        return 0.0
    d = haversine_km(depot_lat, depot_lon, order[0].lat, order[0].lon)
    for i in range(len(order) - 1):
        d += haversine_km(order[i].lat, order[i].lon, order[i + 1].lat, order[i + 1].lon)
    d += haversine_km(order[-1].lat, order[-1].lon, depot_lat, depot_lon)
    return d


def _flat_dist2(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    """Küçük bölge içinde küme ataması için ucuz kare-mesafe (sıralama amaçlı)."""
    return (a_lat - b_lat) ** 2 + (a_lon - b_lon) ** 2


KMEANS_ITERATIONS = 25


def kmeans_clusters(
    bins: list[BinLike],
    k: int,
    iterations: int = KMEANS_ITERATIONS,
) -> list[list[BinLike]]:
    """
    Basit Lloyd K-means, düz lat/lon üzerinde (bölge küçük olduğundan
    flat-earth yaklaşımı yeterli — bkz. simulation_engine._dist_to_segment_km).

    Centroid'ler yakınsadıktan sonra, her kümeyi en fazla ceil(n/k) bin ile
    sınırlayan dengeli bir atama yapılır — böylece her küme yaklaşık bir
    kamyon rotası (FIXED_ROUTE_SIZE) büyüklüğünde kalır.
    """
    n = len(bins)
    if n == 0:
        return []
    k = max(1, min(k, n))
    if k == 1:
        return [list(bins)]

    rng       = random.Random(42)   # deterministik başlangıç → tutarlı rotalar
    all_bins  = list(bins)
    centroids = [(b.lat, b.lon) for b in rng.sample(all_bins, k)]

    for _ in range(iterations):
        nearest = [
            min(range(k), key=lambda c: _flat_dist2(b.lat, b.lon, *centroids[c]))
            for b in all_bins
        ]
        sums = [[0.0, 0.0, 0] for _ in range(k)]
        for b, c in zip(all_bins, nearest):
            sums[c][0] += b.lat
            sums[c][1] += b.lon
            sums[c][2] += 1
        new_centroids = [
            (sums[c][0] / sums[c][2], sums[c][1] / sums[c][2]) if sums[c][2] else centroids[c]
            for c in range(k)
        ]
        if new_centroids == centroids:
            break
        centroids = new_centroids

    # Kapasite dengeli atama: en yakın (kendi merkezine en bağlı) noktalar
    # önce yerleşir; her küme ceil(n/k) dolunca bir sonraki en yakın
    # merkeze taşar.
    cap   = math.ceil(n / k)
    order = sorted(
        range(n),
        key=lambda i: min(_flat_dist2(all_bins[i].lat, all_bins[i].lon, *c) for c in centroids),
    )
    clusters: list[list[BinLike]] = [[] for _ in range(k)]
    for i in order:
        b     = all_bins[i]
        prefs = sorted(range(k), key=lambda c: _flat_dist2(b.lat, b.lon, *centroids[c]))
        for c in prefs:
            if len(clusters[c]) < cap:
                clusters[c].append(b)
                break
        else:
            least = min(range(k), key=lambda c: len(clusters[c]))
            clusters[least].append(b)

    return [c for c in clusters if c]
