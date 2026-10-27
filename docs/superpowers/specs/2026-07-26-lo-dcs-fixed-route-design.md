# LO-DCS: Fixed-route dünyası algoritma değişimi

## Bağlam

Simülasyonda iki paralel dünya var: `algo` (DPET — dinamik dispatch) ve `fixed`
(startup'ta bir kez hesaplanan sabit rotalar). `fixed` dünyası şu ana kadar
Sweep (depot'tan açıya göre sıralama) + Nearest-Neighbor + 2-opt kullanıyordu
(`simulation_engine.py::_precompute_fixed_routes`).

Amaç: `fixed` dünyasının rota kurma algoritmasını, "Route optimization in
urban waste management using locally adjusted discrete cuckoo search"
makalesindeki **LO-DCS (Locally Optimized Discrete Cuckoo Search)**
algoritmasıyla değiştirmek. Böylece DPET karşılaştırması artık "sabit/naif
sweep rota" yerine literatürdeki bir metasezgisel algoritmaya karşı yapılmış
olacak.

## Kapsam

- Yeni modül: `backend/app/lo_dcs.py`
- Değişen dosya: `backend/app/simulation_engine.py`
  (`_precompute_fixed_routes` ve artık kullanılmayan yardımcılar)
- Runtime dispatch/truck/KPI mantığında değişiklik yok — `_fixed_routes`
  formatı (`list[list[Stop]]`) korunuyor.

## Tasarım

### `kmeans_clusters(bins, k, iterations=25) -> list[list[BinLike]]`

Düz lat/lon üzerinde basit Lloyd K-means (yeni bağımlılık yok — mevcut
`_dist_to_segment_km`'deki flat-earth yaklaşımıyla tutarlı). Boş küme
oluşursa en büyük kümeden en uzak noktayı alıp yeniden atar.

`k = ceil(len(bins) / FIXED_ROUTE_SIZE)` → her küme bir kamyon rotası
büyüklüğünde (kapasite uyumu, mevcut sistemin FIXED_ROUTE_SIZE=20 mantığıyla
birebir).

### `lo_dcs_route(cluster_bins, depot_lat, depot_lon, *, population_size=50, max_iterations=200, discovery_pa=0.25) -> list[Stop]`

Makalenin Algorithm 2'sini uygular:

1. N rastgele permütasyon (nest) üret; her biri `cluster_bins`'in bir
   sıralaması.
2. Fitness = depot → duraklar → depot toplam km (haversine). Global best
   `x*`'i belirle.
3. `t = 1..T`:
   - Her nest için discrete random walk: 2 rastgele pozisyon seç, swap et,
     fitness'ı değerlendir; iyiyse kabul et (elitizm doğal olarak korunur).
   - Popülasyonun en kötü `Pa` oranını (aşağı yuvarlanmış, min 0) rastgele
     yeni permütasyonlarla değiştir (klasik CS'in "discovery" kuralı —
     makalede Pa parametresi bunun için var).
   - Global best güncellenirse, üzerinde tam 2-opt çalıştır (mevcut
     `_two_opt_route` mantığı buraya taşınır).
4. `x*`'i döndür.

Varsayılan parametreler makalenin Tablo 1'i ile birebir: N=50, Pa=0.25,
T=200. Gerçek DB'de 300 bin var → 15 küme; bu ölçekte saf Python'da
saniyenin altında biter, hız kaygısı yok.

### `simulation_engine.py` değişikliği

`_precompute_fixed_routes`:

```
k = ceil(len(all_bins) / FIXED_ROUTE_SIZE)
clusters = kmeans_clusters(list(self.fixed_bins.values()), k)
self._fixed_routes = [
    lo_dcs_route(cluster, self.depot_lat, self.depot_lon)
    for cluster in clusters if cluster
]
```

Artık kullanılmayan `_nearest_neighbor` ve `_angle_from_depot` kaldırılır;
`_two_opt_route` `lo_dcs.py`'ye taşınır (import edilerek başka yerde
kullanılıyorsa korunur — kontrol edildi, sadece burada kullanılıyordu).
Dosya başı docstring (satır 1-16) ve `_precompute_fixed_routes` docstring'i
LO-DCS'i anlatacak şekilde güncellenir.

## Test / Doğrulama

- Backend'i gerçek Postgres (300 bin) ile `uvicorn` üzerinden başlat, açılış
  loglarında hata olmadığını doğrula.
- Frontend'i başlatıp simülasyonu çalıştırarak "fixed" dünyasında kamyonların
  rota alıp hareket ettiğini gözlemle.
