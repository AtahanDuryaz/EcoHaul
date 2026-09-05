"""
K-Means + Ant Colony Optimization (k-means-ACO).

Kaynak: Kim, J., Manna, A., Roy, A. & Moon, I., "Clustered vehicle routing
problem for waste collection with smart operational management approaches",
Intl. Trans. in Op. Res. 32(2), 863–887 (2023).

fixed dünyası için sabit rota kurucu alternatiflerinden biri (bkz.
route_common.py paylaşılan K-Means kümeleme için). Her küme bağımsız olarak
Ant Colony Optimization (ACO) ile aranır — makalenin Section 4.2'sindeki
k-means-ACO algoritmasının (Algorithm 3) rota-kurma çekirdeği:

  - Feromon τ_ij = 1/√d_ij ile başlatılır (Section 4.2.2).
  - Her karınca depodan başlayıp feromon + görünürlük (1/mesafe) ağırlıklı
    rulet-çarkı seçimiyle küme bin'lerini sırayla gezer (Section 4.2.3).
  - Her iterasyon sonunda feromon buharlaşır (ρ) ve o iterasyonun en iyi
    karıncasının rotası üzerine takviye feromon eklenir (elitist Ant
    System — Section 4.2.4/4.2.5).

Not: Makalenin metin içi formülü δ1 tek başına feromon üssü olarak
kullanılıyor gibi görünse de, Tablo 2 ayrıca α (feromon) ve β (görünürlük)
üslerini de parametre olarak listeler. Bu modül ikisini standart ACO
gösterimiyle (τ^α · η^β) birleştirir — hem makalenin kendi parametre
tablosuna hem de TSP için bilinen sağlam ACO pratiğine sadık kalır. Karınca
depodan başlar/depoya döner (makalenin rastgele-bin başlangıcı yerine);
gerçek bir kamyon rotası depoyu çapa alması gerektiğinden bu, LO-DCS'teki
depo-merkezli fitness uyarlamasıyla aynı kategoriden pratik bir zorunluluktur.

Startup'ta bir kez çalışır (sabit rotalar); simülasyon tick döngüsünde
kullanılmaz.
"""
from __future__ import annotations

import random

from .dpet import Stop
from .route_common import BinLike, haversine_km

# ══════════════════════════════════════════════════════════════════════════
# Parametreler — makale Tablo 2 ile birebir (α=1, β=2, ρ=0.5, n=300 karınca)
# ══════════════════════════════════════════════════════════════════════════

ALPHA          = 1.0    # feromon üssü
BETA           = 2.0    # görünürlük (1/mesafe) üssü
RHO            = 0.5    # buharlaşma oranı
N_ANTS         = 300
MAX_ITERATIONS = 100


def aco_route(
    cluster_bins: list[BinLike],
    depot_lat: float,
    depot_lon: float,
    *,
    n_ants: int = N_ANTS,
    max_iterations: int = MAX_ITERATIONS,
    alpha: float = ALPHA,
    beta: float = BETA,
    rho: float = RHO,
    rng: random.Random | None = None,
) -> list[Stop]:
    n = len(cluster_bins)
    if n == 0:
        return []
    if n <= 2:
        return [Stop(b.bin_id, b.lat, b.lon) for b in cluster_bins]

    rng = rng or random.Random()

    # Düğüm 0 = depot, 1..n = küme bin'leri. Mesafe/görünürlük matrisi
    # bir kez hesaplanır — haversine tekrar tekrar çağrılmaz.
    lats = [depot_lat] + [b.lat for b in cluster_bins]
    lons = [depot_lon] + [b.lon for b in cluster_bins]
    N    = n + 1
    dist = [[0.0] * N for _ in range(N)]
    for i in range(N):
        for j in range(i + 1, N):
            d = max(haversine_km(lats[i], lons[i], lats[j], lons[j]), 1e-6)
            dist[i][j] = dist[j][i] = d

    pher    = [[1.0 / (dist[i][j] ** 0.5) if i != j else 0.0 for j in range(N)] for i in range(N)]
    vis_pow = [[(1.0 / dist[i][j]) ** beta if i != j else 0.0 for j in range(N)] for i in range(N)]

    def _tour_length(tour: list[int]) -> float:
        d = dist[0][tour[0]]
        for a, b in zip(tour, tour[1:]):
            d += dist[a][b]
        d += dist[tour[-1]][0]
        return d

    def _build_ant_tour() -> list[int]:
        unvisited = list(range(1, N))
        tour: list[int] = []
        current = 0
        while unvisited:
            pher_row = pher[current]
            vis_row  = vis_pow[current]
            weights  = [(pher_row[j] ** alpha) * vis_row[j] for j in unvisited]
            total    = sum(weights)
            if total <= 0:
                nxt = rng.choice(unvisited)
            else:
                r, acc, nxt = rng.uniform(0, total), 0.0, unvisited[-1]
                for node, w in zip(unvisited, weights):
                    acc += w
                    if acc >= r:
                        nxt = node
                        break
            tour.append(nxt)
            unvisited.remove(nxt)
            current = nxt
        return tour

    best_tour: list[int] = list(range(1, N))
    best_len  = _tour_length(best_tour)

    for _ in range(max_iterations):
        iter_best_tour: list[int] | None = None
        iter_best_len  = float("inf")

        for _ in range(n_ants):
            tour   = _build_ant_tour()
            length = _tour_length(tour)
            if length < iter_best_len:
                iter_best_tour, iter_best_len = tour, length

        # Buharlaşma (Eq. 14)
        for i in range(N):
            row = pher[i]
            for j in range(N):
                if i != j:
                    row[j] *= (1.0 - rho)

        # Elitist takviye — iterasyonun en iyi karıncasının rotasına feromon ekle
        if iter_best_tour is not None:
            deposit = rho / max(iter_best_len, 1e-6)
            prev = 0
            for node in iter_best_tour:
                pher[prev][node] += deposit
                pher[node][prev] += deposit
                prev = node
            pher[prev][0] += deposit
            pher[0][prev] += deposit

            if iter_best_len < best_len:
                best_tour, best_len = iter_best_tour, iter_best_len

    return [Stop(cluster_bins[i - 1].bin_id, cluster_bins[i - 1].lat, cluster_bins[i - 1].lon)
            for i in best_tour]
