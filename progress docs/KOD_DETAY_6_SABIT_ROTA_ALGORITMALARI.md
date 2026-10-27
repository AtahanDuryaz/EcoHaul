# Kod Detaylı Açıklama — Bölüm 6: Sabit Rota Algoritmaları (LO-DCS / ACO / HHO)

> Bu bölüm, `fixed` dünyasının rota kurma algoritmasını akademik literatürden üç
> farklı metasezgiselle değiştirilebilir hâle getiren değişikliği belgeler.
> Önceden `fixed` dünyası basit bir Sweep (açı sıralama) + Nearest-Neighbor + 2-opt
> kullanıyordu; artık üç yayınlanmış makalenin algoritmalarından biri seçilebiliyor
> ve seçim canlı panodaki dropdown'dan yapılıyor.
>
> **Güncelleme (v2 — §11):** İlk sürümde üç algoritma da sadece rota *sıralamasını*
> değiştiriyordu; dispatch mantığı (her gün TÜM bin'leri gez) `lo_dcs`'in eski
> statik modeliyle aynıydı. Kim et al. (2023) ve Huang et al. (2026) makaleleri
> aslında **dinamik/doluluk-farkında** dispatch sistemleri tanımlıyor — bu yüzden
> `aco` ve `hho` artık kendi makalelerindeki gibi gerçekten dinamik çalışıyor
> (bkz. §11). `lo_dcs` statik kalmaya devam ediyor çünkü o makalenin kendisi de
> statik bir VRP çözümü.

← Önceki: [Bölüm 5 — ESP32 ve Frontend](KOD_DETAY_5_ESP32_VE_FRONTEND.md)

---

## 0. Neden Bu Değişiklik?

Projenin akademik özü, **DPET algoritmasının sabit rotalara göre tasarrufunu**
ölçmek. Eskiden "sabit rota" tarafı Sweep+NN+2-opt gibi kasıtlı olarak zayıf bir
sezgiselle kuruluyordu (kod yorumunda da yazıyordu: *"Truck uzak bin'e gidip geri
döner → fixed rotalar daha uzun km yapar"*). Bu, DPET'i güzel gösteren ama
literatürle karşılaştırma yapmayan bir kurulumdu.

Şimdi `fixed` dünyası, üç gerçek akademik makalenin algoritmasıyla kurulabiliyor:

| Anahtar | Makale | Yöntem |
|---|---|---|
| `lo_dcs` | Goswami, Poornima N. V., Prabu P. & Saudagar, *"Route optimization in urban waste management using locally adjusted discrete cuckoo search"*, Scientific Reports 16:10097 (2026) | K-Means + Discrete Cuckoo Search + 2-opt |
| `aco` | Kim, J., Manna, A., Roy, A. & Moon, I., *"Clustered vehicle routing problem for waste collection with smart operational management approaches"*, Intl. Trans. in Op. Res. 32(2), 863–887 (2023) | K-Means + Ant Colony Optimization |
| `hho` | Huang, M., Qu, T., Wan, M. & Huang, G. Q., *"Dynamic Collection Routing Optimization for Domestic Waste with Mixed Fleets"*, Systems 14(5), 461 (2026) | K-Means + İyileştirilmiş Harris Hawks Optimization |

Böylece karşılaştırma artık **"DPET vs. üç farklı literatür algoritması"** olarak
yapılabiliyor.

---

## 1. Genel Mimari

```
                    load_bins() / algoritma değişimi
                              │
                              ▼
                 route_common.kmeans_clusters(bins, k)
                 k = ceil(bin_sayısı / FIXED_ROUTE_SIZE)
                 (her küme ≈ bir kamyonluk kapasite, 20 durak)
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        lo_dcs_route()   aco_route()     hho_route()
      (cuckoo search)  (ant colony)  (improved HHO)
              │               │               │
              └───────────────┴───────────────┘
                              ▼
                  self._fixed_routes: list[list[Stop]]
                              │
                              ▼
              _job_dispatch_fixed() (her gün 06:00, değişmedi)
```

Üç algoritma da **aynı imzayı** paylaşır: `(cluster_bins, depot_lat, depot_lon) -> list[Stop]`.
Bu sayede `simulation_engine.py` hangi algoritmanın çalıştığını bilmeden, bir
sözlükten (`FIXED_ROUTE_ALGORITHMS`) fonksiyonu çekip çağırıyor.

Kapasite ile ilgili tek ortak karar: **K-Means küme sayısı** `k = ceil(bin/20)`
olacak şekilde otomatik hesaplanıyor (makalelerin kendi veri setlerine özel sabit
K değerleri yerine). Böylece her küme gerçek kamyon kapasitesiyle (20 durak =
%100 dolu kamyon) örtüşüyor; üç algoritma da bu ortak kısıtı paylaşıyor.

---

## 2. Yeni Dosya: `route_common.py`

Üç algoritmanın da ihtiyaç duyduğu geometri (haversine, rota uzunluğu) ve
K-Means kümeleme burada tek yerde toplandı — önceden `lo_dcs.py` içinde
tekrar edecekti, dosyalar arası kopyayı önlemek için ayrıldı.

```python
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
```

**Neden "kapasite dengeli atama" gerekti?** Standart K-Means küme boyutlarını
dengelemez (bazı kümeler 5 bin, bazıları 40 bin olabilir). Kamyon kapasitesi
gerçek bir kısıt olduğundan, her kümenin **en fazla `ceil(n/k)`** bin
(yaklaşık 20) içermesini zorlayan bir son-atama adımı eklendi: noktalar kendi
merkezlerine olan yakınlık sırasına göre yerleştirilir, kapasite dolan küme
bir sonraki en yakın merkeze devreder.

---

## 3. `lo_dcs.py` — Discrete Cuckoo Search + 2-opt (Goswami et al. 2026)

Önceki sürümden fark: `route_common`'a taşınan ortak kod çıkarıldı, sadece
cuckoo search'e özgü kısım kaldı.

```python
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
```

**Fikir birebir makaleden, tek uyarlama:** Fitness, makalenin "ilk düğüme
dönüş" formülü yerine **depoya dönüş** ile hesaplanıyor (`route_length_km` =
depot→duraklar→depot). Gerçek bir kamyon depodan çıkıp depoya dönmek zorunda;
bu, kod tabanındaki diğer tüm mesafe hesaplarıyla da tutarlı.

---

## 4. Yeni Dosya: `aco_route.py` — K-Means + Ant Colony Optimization (Kim et al. 2023)

```python
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
```

---

## 5. Yeni Dosya: `hho_route.py` — İyileştirilmiş Harris Hawks Optimization (Huang et al. 2026)

```python
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
```

---

## 6. `simulation_engine.py` — Algoritma Kayıt Defteri ve Seçim Mekanizması

### 6.1 Import'lar ve kayıt defteri (dosya başı)

```python
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
```

### 6.2 `__init__` içine eklenen alan

```python
self._fixed_routes: list[list[Stop]] = []
self.fixed_algorithm: str = DEFAULT_FIXED_ALGORITHM
```

### 6.3 `_precompute_fixed_routes` — artık algoritma bağımsız

```python
def _precompute_fixed_routes(self) -> None:
    """
    Seçili algoritma ile sabit rota grupları oluştur (bkz.
    FIXED_ROUTE_ALGORITHMS — lo_dcs.py / aco_route.py / hho_route.py).

    1. K-Means ile bin'ler kamyon kapasitesi büyüklüğünde (≈ FIXED_ROUTE_SIZE)
       kümelere bölünür (route_common.kmeans_clusters).
    2. Her küme bağımsız olarak seçili metasezgisel (discrete cuckoo search,
       ant colony optimization veya improved HHO) ile sıralanır.
    """
    all_bins = list(self.fixed_bins.values())
    self._fixed_routes.clear()
    if not all_bins:
        return

    build_route = FIXED_ROUTE_ALGORITHMS[self.fixed_algorithm]
    k = math.ceil(len(all_bins) / FIXED_ROUTE_SIZE)
    for cluster in kmeans_clusters(all_bins, k):
        route = build_route(cluster, self.depot_lat, self.depot_lon)
        if route:
            self._fixed_routes.append(route)
```

### 6.4 Yeni metod: `set_fixed_algorithm`

```python
def set_fixed_algorithm(self, algorithm: str) -> bool:
    """
    Fixed dünyasının rota kurma algoritmasını değiştir ve rotaları yeniden
    hesapla. Simülasyon çalışırken çağrılamaz — sağdaki dropdown bu yüzden
    is_running iken devre dışı bırakılır (bkz. routers/simulation.py).

    Returns: başarılıysa True, geçersiz algoritma adında veya simülasyon
    çalışırken çağrılırsa False.
    """
    if self.is_running or algorithm not in FIXED_ROUTE_ALGORITHMS:
        return False
    self.fixed_algorithm = algorithm
    self._precompute_fixed_routes()
    self.fixed_trucks.clear()
    self.fixed_kpis          = self._zero_kpis()
    self._fixed_route_cursor = 0
    self._last_fixed_day_key = None
    return True
```

### 6.5 `state_snapshot()` içine eklenen alan

```python
"depot_lon":        self.depot_lon,
"fixed_algorithm":  self.fixed_algorithm,
```

### 6.6 Kaldırılanlar

`_nearest_neighbor()` ve `_two_opt_route()` (eski Sweep+NN+2-opt yardımcıları)
ve açı-sıralama (`_angle_from_depot`) mantığı tamamen silindi — artık hiçbir
yerde kullanılmıyorlar, yerlerini `route_common.py` + üç algoritma modülü aldı.

---

## 7. `routers/simulation.py` — Yeni Endpoint

```python
@router.patch("/fixed-algorithm")
async def set_fixed_algorithm(algorithm: str = Body(..., embed=True)):
    if algorithm not in FIXED_ROUTE_ALGORITHMS:
        raise HTTPException(
            status_code=422,
            detail=f"Geçersiz algoritma. Kullanılabilir: {list(FIXED_ROUTE_ALGORITHMS)}",
        )
    if engine.is_running:
        raise HTTPException(
            status_code=409,
            detail="Simülasyon çalışırken fixed algoritması değiştirilemez. Önce durdurun.",
        )
    # ACO/HHO gibi ağır metasezgiseller ~10-25s sürebilir; event loop'u
    # kilitlememek için ayrı thread'de çalıştırılır (diğer polling istekleri
    # bu sırada normal yanıt vermeye devam eder).
    await asyncio.to_thread(engine.set_fixed_algorithm, algorithm)
    return {"fixed_algorithm": engine.fixed_algorithm}
```

`asyncio.to_thread` kullanımı önemli: ACO ~10-25 saniye sürebiliyor (bkz. §9
Performans Ölçümleri). Bu süre boyunca FastAPI'nin tek event loop'u bloklanırsa
frontend'in her saniye attığı `live-state` polling'i de donar. `to_thread` ile
hesaplama ayrı bir thread'de yapılır, event loop diğer isteklere yanıt vermeye
devam eder (bkz. §9.2'deki eşzamanlılık testi).

---

## 8. Frontend — Dropdown Seçici

### 8.1 `services/api.js`

```javascript
export const setFixedAlgorithm = (algorithm)       => api.patch('/api/simulation/fixed-algorithm', { algorithm })
```

### 8.2 `SimulationPage.jsx` — sabitler

```javascript
const FIXED_ALGO_OPTIONS = [
  { value: 'lo_dcs', label: 'LO-DCS — Cuckoo Search (Goswami vd. 2026)' },
  { value: 'aco',    label: 'K-Means + ACO (Kim vd. 2023)' },
  { value: 'hho',    label: 'İyileştirilmiş HHO (Huang vd. 2026)' },
]
```

### 8.3 Yeni bileşen: `FixedAlgoSelect`

```jsx
function FixedAlgoSelect({ value, disabled, switching, onChange }) {
  return (
    <div className="opc-algo-select-row">
      <label htmlFor="fixed-algo-select" className="opc-algo-select-label">
        Rota Algoritması
      </label>
      <select
        id="fixed-algo-select"
        className="opc-algo-select"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        {FIXED_ALGO_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
      {switching && <span className="opc-algo-select-loading">Hesaplanıyor…</span>}
    </div>
  )
}
```

### 8.4 `ColPanel` — sadece `fixed` panelde render edilir, haritanın üstünde

```jsx
function ColPanel({
  title, accent, kpis, trucks, bins, showTraffic, trafficToken, depotLat, depotLon,
  isRunning, fixedAlgorithm, algoSwitching, onFixedAlgorithmChange,
}) {
  // ...
  return (
    <div className={`opc-col opc-col-${accent}`}>
      {/* ...KPI chip'leri, TruckDots... */}

      {accent === 'fixed' && (
        <FixedAlgoSelect
          value={fixedAlgorithm || 'lo_dcs'}
          disabled={isRunning || algoSwitching}
          switching={algoSwitching}
          onChange={onFixedAlgorithmChange}
        />
      )}

      <div className="opc-map-area">
        {/* ...SimMap... */}
      </div>
    </div>
  )
}
```

`disabled={isRunning || algoSwitching}` — simülasyon çalışırken **veya**
sunucudan cevap beklenirken dropdown kilitli kalır (istenen davranış: "sağ
haritanın üstünden simülasyon başladığında değiştirilemesin").

### 8.5 Ana bileşende state + handler

```javascript
const [fixedAlgorithm, setFixedAlgorithmState] = useState('lo_dcs')
const [algoSwitching, setAlgoSwitching]         = useState(false)

// pollState() içinde:
if (data.fixed_algorithm) setFixedAlgorithmState(data.fixed_algorithm)

const handleFixedAlgorithmChange = async (algorithm) => {
  if (isRunning || algorithm === fixedAlgorithm) return
  setAlgoSwitching(true)
  try {
    await setFixedAlgorithm(algorithm)
    setFixedAlgorithmState(algorithm)
    await pollState()
  } catch {
    // Sunucu reddettiyse (örn. bu sırada simülasyon başladıysa) gerçek durumu geri çek
    await pollState()
  } finally {
    setAlgoSwitching(false)
  }
}
```

### 8.6 `SimulationPage` render — sadece `fixed` `ColPanel`'e prop geçişi

```jsx
<ColPanel
  title="SABİT ROTA"
  accent="fixed"
  kpis={fixedKPIs}
  trucks={fixedTrucks}
  bins={fixedBins}
  showTraffic={showTraffic}
  trafficToken={trafficToken}
  depotLat={depotLat}
  depotLon={depotLon}
  isRunning={isRunning}
  fixedAlgorithm={fixedAlgorithm}
  algoSwitching={algoSwitching}
  onFixedAlgorithmChange={handleFixedAlgorithmChange}
/>
```

### 8.7 `App.css` — koyu tema ile uyumlu stil

```css
/* ── Fixed dünyası: rota algoritması seçici ── */
.opc-algo-select-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  background: #09111e;
  border-bottom: 1px solid #0e1a2e;
  flex-shrink: 0;
}

.opc-algo-select-label {
  font-size: 11px;
  color: #64748b;
  white-space: nowrap;
}

.opc-algo-select {
  flex: 1;
  min-width: 0;
  font-size: 12px;
  color: #e2e8f0;
  background: #0e1a2e;
  border: 1px solid #1e293b;
  border-radius: 4px;
  padding: 3px 6px;
}

.opc-algo-select:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.opc-algo-select-loading {
  font-size: 11px;
  color: #f59e0b;
  white-space: nowrap;
}
```

---

## 9. Doğrulama / Performans Ölçümleri

Gerçek veritabanındaki 300 bin ile (15 küme × 20 durak) yapılan testler:

### 9.1 Her algoritmanın tek seferlik hesaplama süresi

| Algoritma | Süre | Rota sayısı | Durak/rota | Benzersiz mi? | Tam kapsama mı? |
|---|---|---|---|---|---|
| `lo_dcs` | ~4.5s | 15 | 20 | ✅ | ✅ |
| `aco`    | ~24.5s | 15 | 20 | ✅ | ✅ |
| `hho`    | ~13.0s | 15 | 20 | ✅ | ✅ |

Üçü de tüm 300 bin'i tekrarsız ve eksiksiz kapsıyor.

### 9.2 Eşzamanlılık testi (event loop kilitlenmiyor mu?)

`aco` algoritmasına geçiş (~19s) arka planda çalışırken `/health` endpoint'ine
istek atıldı:

```
health check while aco is computing: 200 in 0.21s
```

`asyncio.to_thread` sayesinde event loop, ağır hesaplama sırasında da diğer
isteklere anında yanıt veriyor.

### 9.3 API davranış testleri

| Senaryo | Beklenen | Sonuç |
|---|---|---|
| Geçersiz algoritma adı (`"nope"`) | `422` | ✅ |
| Simülasyon çalışırken değiştirme denemesi | `409` | ✅ |
| Simülasyon durdurulmuşken geçerli algoritma | `200` + rotalar yeniden hesaplanır | ✅ |

---

## 10. Kullanım

1. Backend + frontend'i başlat, `/simulation` sayfasını aç.
2. Sağdaki **"SABİT ROTA"** panelinin üstünde, kamyon sayacının hemen
   altında **"Rota Algoritması"** dropdown'u görünür.
3. Simülasyon **durduruluşken** (▶ Başlat'a basılmadan önce veya ⏸ Durdur'dan
   sonra) istediğin algoritmayı seç — seçim anında backend'e gönderilir,
   rotalar yeniden hesaplanır (LO-DCS ~5s, HHO ~13s, ACO ~25s sürebilir;
   bu sırada "Hesaplanıyor…" yazısı görünür).
4. Simülasyon çalışırken dropdown gri/pasif görünür, değiştirilemez.
5. Sol panel (**"ALGORİTMA KPI"** = DPET) bu seçimden hiç etkilenmez —
   karşılaştırma her zaman "DPET vs. seçili sabit-rota algoritması" şeklinde
   kalır.
