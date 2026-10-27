"""
Improved Harris Hawks Optimization (Improved HHO).

Kaynak: Huang, M., Qu, T., Wan, M. & Huang, G. Q., "Dynamic Collection
Routing Optimization for Domestic Waste with Mixed Fleets", Systems 14(5),
461 (2026).

fixed dünyası için sabit rota kurucu alternatiflerinden biri (bkz.
route_common.py paylaşılan K-Means kümeleme için). Her küme bağımsız olarak
makalenin Section 4.1'inde tarif edilen İyileştirilmiş HHO ile aranır:

  - Klasik HHO (Heidari et al. 2019) kaçış enerjisi E ile keşif/sömürü
    fazları arasında geçiş yapar (|E|≥1 keşif; |E|<1 sömürüde yumuşak/sert
    kuşatma ve aşamalı hızlı dalış — Levy uçuşu — varyantlarıyla).
  - Simulated Annealing'in Metropolis kriteri klasik HHO'nun açgözlü kabul
    mekanizmasının yerine geçer: daha kötü çözümler de bir olasılıkla kabul
    edilerek lokal optimadan kaçış kolaylaştırılır (paper Section 4.1,
    Case 1/2).
  - Her iterasyon sonunda GA'dan alınan elit/en-kötü birey pertürbasyonu
    (iki noktalı çaprazlama + mutasyon) popülasyon çeşitliliğini korur.

Not: Orijinal HHO sürekli konum uzayında tanımlıdır; permütasyon (rota
sırası) problemine uyarlamak için random-key kodlaması kullanılır — her
durağa [0,1] aralığında sürekli bir anahtar atanır, rota sırası bu
anahtarların küçükten büyüğe sıralanmasıyla elde edilir (LOV — Largest
Order Value kuralı; sürekli metasezgiselleri permütasyon problemlerine
uyarlamak için literatürde standart bir tekniktir). Makale bu kodlama
adımının ayrıntısını vermez; MATLAB uygulamasının örtük bir parçası olarak
ele alınmıştır.

Startup'ta bir kez çalışır (sabit rotalar); simülasyon tick döngüsünde
kullanılmaz.
"""
from __future__ import annotations

import math
import random

from .dpet import Stop
from .route_common import BinLike, route_length_km

# ══════════════════════════════════════════════════════════════════════════
# Parametreler — makale Tablo 2/5 ile birebir
# ══════════════════════════════════════════════════════════════════════════

POPULATION_SIZE = 100
MAX_ITERATIONS  = 100
SA_INITIAL_TEMP = 1000.0
SA_COOLING_RATE = 0.95
ELITE_POOL_SIZE = 10
LEVY_BETA       = 1.5


def _levy_step(dim: int, rng: random.Random) -> list[float]:
    """Mantegna algoritması ile Levy uçuşu adımı (klasik HHO'nun aynısı)."""
    beta  = LEVY_BETA
    num   = math.gamma(1 + beta) * math.sin(math.pi * beta / 2)
    den   = math.gamma((1 + beta) / 2) * beta * (2 ** ((beta - 1) / 2))
    sigma = (num / den) ** (1 / beta)
    step  = []
    for _ in range(dim):
        u = rng.gauss(0, sigma)
        v = rng.gauss(0, 1)
        step.append(0.01 * u / (abs(v) ** (1 / beta)))
    return step


def hho_route(
    cluster_bins: list[BinLike],
    depot_lat: float,
    depot_lon: float,
    *,
    population_size: int = POPULATION_SIZE,
    max_iterations: int = MAX_ITERATIONS,
    rng: random.Random | None = None,
) -> list[Stop]:
    n = len(cluster_bins)
    if n == 0:
        return []
    if n <= 3:
        return [Stop(b.bin_id, b.lat, b.lon) for b in cluster_bins]

    rng = rng or random.Random()

    def _decode(keys: list[float]) -> list[BinLike]:
        order = sorted(range(n), key=lambda i: keys[i])   # LOV kuralı
        return [cluster_bins[i] for i in order]

    def _fitness(keys: list[float]) -> float:
        return route_length_km(_decode(keys), depot_lat, depot_lon)

    population = [[rng.random() for _ in range(n)] for _ in range(population_size)]
    fitness    = [_fitness(hawk) for hawk in population]

    best_idx   = min(range(population_size), key=lambda i: fitness[i])
    rabbit     = list(population[best_idx])
    rabbit_fit = fitness[best_idx]

    temperature = SA_INITIAL_TEMP

    for t in range(max_iterations):
        x_mean = [sum(hawk[d] for hawk in population) / population_size for d in range(n)]

        for i in range(population_size):
            hawk = population[i]
            e0   = 2 * rng.random() - 1
            e    = 2 * e0 * (1 - t / max_iterations)
            q    = rng.random()

            if abs(e) >= 1:
                # Keşif (exploration)
                if q >= 0.5:
                    rand_hawk = population[rng.randrange(population_size)]
                    r1, r2 = rng.random(), rng.random()
                    new_pos = [
                        rand_hawk[d] - r1 * abs(rand_hawk[d] - 2 * r2 * hawk[d])
                        for d in range(n)
                    ]
                else:
                    r3, r4 = rng.random(), rng.random()
                    new_pos = [(rabbit[d] - x_mean[d]) - r3 * r4 for d in range(n)]
            else:
                # Sömürü (exploitation)
                r     = rng.random()
                j     = 2 * (1 - rng.random())
                delta = [rabbit[d] - hawk[d] for d in range(n)]

                if r >= 0.5 and abs(e) >= 0.5:
                    # Yumuşak kuşatma
                    new_pos = [delta[d] - e * abs(j * rabbit[d] - hawk[d]) for d in range(n)]
                elif r >= 0.5 and abs(e) < 0.5:
                    # Sert kuşatma
                    new_pos = [rabbit[d] - e * abs(delta[d]) for d in range(n)]
                else:
                    # Aşamalı hızlı dalışlı yumuşak/sert kuşatma (Levy uçuşu)
                    base = x_mean if abs(e) < 0.5 else hawk
                    y = [rabbit[d] - e * abs(j * rabbit[d] - base[d]) for d in range(n)]
                    y = [min(1.0, max(0.0, v)) for v in y]
                    if _fitness(y) < fitness[i]:
                        new_pos = y
                    else:
                        levy = _levy_step(n, rng)
                        z = [min(1.0, max(0.0, y[d] + levy[d])) for d in range(n)]
                        new_pos = z if _fitness(z) < fitness[i] else hawk

            new_pos = [min(1.0, max(0.0, v)) for v in new_pos]
            new_fit = _fitness(new_pos)

            # Metropolis kabul kriteri (SA) — klasik HHO'nun açgözlü kabulü yerine
            if new_fit < fitness[i]:
                population[i], fitness[i] = new_pos, new_fit
            else:
                delta_f = new_fit - fitness[i]
                if rng.random() < math.exp(-delta_f / max(temperature, 1e-9)):
                    population[i], fitness[i] = new_pos, new_fit

        # Elit-en kötü birey pertürbasyonu (GA çaprazlama + mutasyon)
        ranked = sorted(range(population_size), key=lambda i: fitness[i])
        elites = ranked[:ELITE_POOL_SIZE]
        worsts = ranked[-ELITE_POOL_SIZE:]
        for elite_idx, worst_idx in zip(elites, worsts):
            a, b = sorted(rng.sample(range(n), 2))
            child = list(population[elite_idx])
            child[a:b] = population[worst_idx][a:b]
            child[rng.randrange(n)] = rng.random()   # mutasyon
            child_fit = _fitness(child)
            if child_fit < fitness[worst_idx]:
                population[worst_idx], fitness[worst_idx] = child, child_fit

        gen_best_idx = min(range(population_size), key=lambda i: fitness[i])
        if fitness[gen_best_idx] < rabbit_fit:
            rabbit, rabbit_fit = list(population[gen_best_idx]), fitness[gen_best_idx]

        temperature *= SA_COOLING_RATE

    return [Stop(b.bin_id, b.lat, b.lon) for b in _decode(rabbit)]
