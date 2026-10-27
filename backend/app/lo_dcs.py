"""
LO-DCS — Locally Optimized Discrete Cuckoo Search.

Kaynak: Goswami, Poornima N. V., Prabu P. & Saudagar, "Route optimization in
urban waste management using locally adjusted discrete cuckoo search: a
hybrid metaheuristic approach", Scientific Reports 16:10097 (2026).

fixed dünyası için sabit rota kurucu seçeneklerinden biri (bkz. route_common.py
paylaşılan K-Means kümeleme için). Her küme bağımsız olarak discrete cuckoo
search ile aranır:

  - N rastgele permütasyon (nest) ile başla.
  - Her iterasyonda: discrete random walk (2 pozisyon swap) ile komşu çözüm
    üret, iyiyse kabul et.
  - En kötü Pa oranındaki nest'i rastgele yenileriyle değiştir (klasik
    cuckoo search'ün "discovery / abandon" kuralı).
  - Global best değiştiğinde üzerinde tam 2-opt çalıştır (lokal iyileştirme
    — makalenin Step 5'i).

Startup'ta bir kez çalışır (sabit rotalar); simülasyon tick döngüsünde
kullanılmaz.
"""
from __future__ import annotations

import random

from .dpet import Stop
from .route_common import BinLike, route_length_km

# ══════════════════════════════════════════════════════════════════════════
# Parametreler — makale Tablo 1 ile birebir (Population=50, Pa=0.25, T=200)
# ══════════════════════════════════════════════════════════════════════════

POPULATION_SIZE = 50
MAX_ITERATIONS  = 200
DISCOVERY_PA    = 0.25


def _two_opt(order: list[BinLike], depot_lat: float, depot_lon: float) -> list[BinLike]:
    """Tam 2-opt: kesişen bacakları çöz, yakınsayana kadar tekrarla."""
    if len(order) < 4:
        return order

    best     = list(order)
    best_len = route_length_km(best, depot_lat, depot_lon)
    improved = True
    while improved:
        improved = False
        for i in range(len(best) - 1):
            for j in range(i + 2, len(best)):
                cand     = best[:i + 1] + best[i + 1:j + 1][::-1] + best[j + 1:]
                cand_len = route_length_km(cand, depot_lat, depot_lon)
                if cand_len < best_len - 1e-6:
                    best, best_len, improved = cand, cand_len, True
                    break
            if improved:
                break
    return best


def lo_dcs_route(
    cluster_bins: list[BinLike],
    depot_lat: float,
    depot_lon: float,
    *,
    population_size: int = POPULATION_SIZE,
    max_iterations: int = MAX_ITERATIONS,
    discovery_pa: float = DISCOVERY_PA,
    rng: random.Random | None = None,
) -> list[Stop]:
    """
    Tek bir kümeyi (≈ bir kamyon rotası) permütasyon uzayında arar.

    Adımlar makalenin Algorithm 2'sine karşılık gelir:
      1. N rastgele permütasyon (nest) üret, fitness'larını hesapla.
      2. T iterasyon: discrete random walk → kabul; en kötü Pa'yı
         discovery ile yenile; global best değiştiyse 2-opt uygula.
      3. En iyi rotayı Stop listesi olarak döndür.
    """
    n = len(cluster_bins)
    if n == 0:
        return []
    if n <= 3:
        # Trivial permütasyon uzayı — arama gereksiz, direkt sırayı döndür.
        return [Stop(b.bin_id, b.lat, b.lon) for b in cluster_bins]

    rng = rng or random.Random()

    def _random_perm() -> list[BinLike]:
        perm = list(cluster_bins)
        rng.shuffle(perm)
        return perm

    population = [_random_perm() for _ in range(population_size)]
    fitness    = [route_length_km(p, depot_lat, depot_lon) for p in population]

    best_idx = min(range(population_size), key=lambda i: fitness[i])
    best     = list(population[best_idx])
    best_fit = fitness[best_idx]

    n_abandon = int(discovery_pa * population_size)

    for _ in range(max_iterations):
        # 4.1 — her nest için discrete random walk (permütasyon-koruyan swap)
        for i in range(population_size):
            p, q = rng.sample(range(n), 2)
            candidate = list(population[i])
            candidate[p], candidate[q] = candidate[q], candidate[p]
            cand_fit = route_length_km(candidate, depot_lat, depot_lon)
            if cand_fit < fitness[i]:
                population[i], fitness[i] = candidate, cand_fit

        # 4.2/4.3 — sırala; en kötü Pa oranını discovery ile değiştir
        # (en iyiler dokunulmadan kalır → elitizm doğal olarak korunur)
        ranked = sorted(range(population_size), key=lambda i: fitness[i])
        for idx in ranked[population_size - n_abandon:]:
            fresh          = _random_perm()
            population[idx] = fresh
            fitness[idx]    = route_length_km(fresh, depot_lat, depot_lon)

        # 4.4/4.5 — global best güncelle, değiştiyse 2-opt ile lokal iyileştir
        gen_best_idx = min(range(population_size), key=lambda i: fitness[i])
        if fitness[gen_best_idx] < best_fit:
            refined  = _two_opt(list(population[gen_best_idx]), depot_lat, depot_lon)
            best     = refined
            best_fit = route_length_km(refined, depot_lat, depot_lon)
            population[gen_best_idx], fitness[gen_best_idx] = best, best_fit

    return [Stop(b.bin_id, b.lat, b.lon) for b in best]
