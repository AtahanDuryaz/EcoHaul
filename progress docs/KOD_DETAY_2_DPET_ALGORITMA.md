# Kod Detaylı Açıklama — Bölüm 2: DPET Algoritması (`dpet.py`)

> **DPET = Dynamic Priority & Efficient Truck dispatch.** Projenin akademik çekirdeği.
> Bu modül "hangi kovalar toplanmalı, hangi sırayla, kaç kamyonla?" sorularına cevap verir.
> 6 katmanlı bir mimari kullanır.

← Önceki: [Bölüm 1 — API ve Veritabanı](KOD_DETAY_1_API_VE_VERITABANI.md)

---

## 2.0 Algoritmanın Hedefleri

Dosyanın başındaki docstring tüm felsefeyi özetler:

```python
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
```

**ETF kavramı (Estimated Time to Full):** Bir kovanın **taşmaya ne kadar süresi kaldığı**.
DPET'in en güçlü fikri budur — dolmuş kovayı toplamak yerine, **yakında dolacak** kovayı
önceden yakalar. Bu öngörü, taşmayı önlemenin anahtarıdır.

---

## 2.1 Ortak Veri Tipleri

```python
@dataclass
class Stop:
    bin_id: str
    lat: float
    lon: float


class _BinLike(Protocol):
    bin_id: str
    lat: float
    lon: float
    fill_pct: float
    fill_rate: float     # %/sim-saat — ETF hesabı için gerekli
    distance_label: int
    is_anomaly: bool
```

- `Stop` → bir rota durağı (kova kimliği + konum). Basit bir veri taşıyıcı.
- **`_BinLike(Protocol)` → ŞURASI ÖNEMLİ.** Bu bir "duck typing" arayüzü. DPET, içeri gelen
  nesnenin tam olarak hangi sınıf olduğunu **umursamaz** — yeter ki `fill_pct`, `fill_rate`
  gibi alanları olsun. Bu sayede `dpet.py`, `simulation_engine.py`'deki `BinState`'e doğrudan
  bağımlı değildir. Gevşek bağlama (loose coupling) sağlar; modülleri ayrı test edebilirsiniz.

## 2.2 Hacimsel Kapasite Sabitleri

```python
TRUCK_CAPACITY      = 1.0    # kamyon toplam kapasitesi (normalize)
BIN_VOLUME_FRACTION = 0.05   # %100 dolu bir bin kamyonun %5'ini doldurur
FUEL_WEIGHT_FACTOR  = 0.8    # tam dolu kamyon boş kamyona göre %80 daha fazla yakıt yakar
```

- `TRUCK_CAPACITY = 1.0` → kapasite **normalize** edilmiş (0-1 arası). Gerçek litre/ton yerine
  soyut birim kullanır, hesaplar basitleşir.
- `BIN_VOLUME_FRACTION = 0.05` → tam dolu bir kova, kamyonun %5'ini doldurur. Yani bir kamyon
  en fazla ~20 tam dolu kova taşıyabilir (`1.0 / 0.05 = 20`).
- `FUEL_WEIGHT_FACTOR = 0.8` → ağırlık-yakıt ilişkisi. Tam dolu kamyon %80 daha fazla yakar.

## 2.3 Coğrafi Yardımcı — Haversine

```python
def _km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(max(0.0, a)))
```

**Haversine formülü** — iki GPS noktası arasındaki **kuş uçuşu** mesafeyi (km) hesaplar.
Dünya küre olduğu için düz Pisagor yetmez; bu formül küresel geometriyi hesaba katar.
`R = 6371` km (Dünya yarıçapı). `max(0.0, a)` → kayan nokta hatalarının negatif kök
oluşturmasını engeller. Bu fonksiyon algoritmanın her yerinde mesafe için kullanılır.

---

## 2.4 KATMAN 1 — Trafik Modeli

```python
_RUSH_HOURS = frozenset({7, 8, 9, 17, 18, 19})
_PEAK_HOURS = frozenset({6, 10, 16, 20})


def traffic_score(hour: int) -> float:
    """0.0 = boş yol (gece)  →  1.0 = tam tıkanıklık"""
    if hour in _RUSH_HOURS:
        return 0.80
    if hour in _PEAK_HOURS:
        return 0.50
    return 0.20
```

**Bu method ne yapıyor?** Saate göre 0-1 arası trafik skoru döner.
- `_RUSH_HOURS` (sabah 7-9, akşam 17-19) → işe gidiş/dönüş, en yoğun → 0.80.
- `_PEAK_HOURS` (6, 10, 16, 20) → orta yoğunluk → 0.50.
- Diğer tüm saatler (gece dahil) → 0.20.
- `frozenset` kullanımı → değiştirilemez küme; `in` kontrolü O(1) hızında.

Bu skor sonra bin seçiminde kullanılır: yoğun saatte algoritma daha **seçici** olur, sadece
acil kovalara gider (trafik varken yola çıkmak pahalı).

---

## 2.5 KATMAN 2 — Bin Skorlama (5 bileşenli)

### Ağırlıklar

```python
_W_FILL      = 0.40   # anlık doluluk baskısı
_W_ETF       = 0.35   # taşmaya kalan süre — erken yakalamayı ödüllendirir
_W_PROXIMITY = 0.05   # yakın bin → rota verimli (seçimde küçük etki)
_W_TRAFFIC   = 0.12   # az trafikte gönder
_W_DENSITY   = 0.08   # yakın çevredeki yüksek-doluluklu bin yoğunluğu

_ETF_HORIZON        = 24.0   # 24 sim saat içindeki ETF skora katkı yapar
_DENSITY_RADIUS_KM  = 1.0    # yoğunluk hesabı için yarıçap (km)
_DENSITY_MAX_BINS   = 10     # normalizasyon: 10+ bin → yoğunluk skoru = 1.0
_DENSITY_MIN_FILL   = 65.0   # yoğunluk sayımına dahil edilecek minimum doluluk
```

**Ağırlıkların toplamı 1.0** (0.40+0.35+0.05+0.12+0.08). Her bileşen 0-1 arası bir skor üretir,
ağırlığıyla çarpılıp toplanır. **En büyük iki ağırlık:** doluluk (0.40) ve ETF (0.35) — yani
algoritma "ne kadar dolu" ve "ne kadar acil dolacak" sorularına en çok önem verir.

### ETF hesabı

```python
def _etf_hours(fill_pct: float, fill_rate: float) -> float:
    """Mevcut doluluk ve hıza göre taşmaya kalan sim saat. fill_rate=0 → ∞"""
    if fill_rate <= 0:
        return float("inf")
    return max(0.0, (100.0 - fill_pct) / fill_rate)
```

**Basit ama kritik:** kalan boşluk (`100 - fill_pct`) bölü dolma hızı (`fill_rate`, %/saat)
= taşmaya kalan saat. Örnek: %70 dolu, saatte %10 doluyorsa → `(100-70)/10 = 3 saat`.
`fill_rate <= 0` ise kova hiç dolmuyor → sonsuz (asla taşmaz).

### Yoğunluk sayımı

```python
def _count_nearby_bins(lat, lon, bins, radius_km, min_fill) -> int:
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
```

Bir kovanın 1 km çevresinde kaç tane **dolu** (≥%65) komşusu var? Çok komşu varsa, o bölgeye
gitmek "verimli" demektir (tek seferde çok kova toplanır). `< 1e-6` kontrolü → kovanın kendisini
saymamak için (mesafe ~0 ise aynı kova).

### Ana skorlama fonksiyonu

```python
def score_bin(fill_pct, fill_rate, distance_label, traffic, density_norm=0.0) -> float:
    fill_urgency = (fill_pct / 100.0) ** 2
    if fill_pct >= 85.0:
        boost = (fill_pct - 85.0) / 15.0          # 0→1 as fill_pct goes 85→100
        fill_urgency += boost * (1.0 - fill_urgency)  # smooth ceiling push
    etf          = _etf_hours(fill_pct, fill_rate)
    etf_urgency  = max(0.0, 1.0 - etf / _ETF_HORIZON)   # 8h+ → 0, 0h → 1
    proximity    = 1.0 - (distance_label - 1) / 2.0
    traffic_ok   = 1.0 - traffic

    return (_W_FILL * fill_urgency
            + _W_ETF * etf_urgency
            + _W_PROXIMITY * proximity
            + _W_TRAFFIC * traffic_ok
            + _W_DENSITY * density_norm)
```

**Her bileşeni tek tek:**
- **`fill_urgency = (fill_pct / 100.0) ** 2` → ŞURASI ÖNEMLİ.** Doluluğun **karesi** alınır.
  Neden kare? Doğrusal olsaydı %90 dolu kova, %45 dolunun 2 katı önemli olurdu. Kare ile
  **4 katı** olur. Yani kritik kovalar orantısız şekilde öne çıkar — istenen davranış.
- **85% üstü boost:** `(fill_pct - 85)/15` ile 85→100 arasında ekstra ivme. `boost * (1 - fill_urgency)`
  formülü skoru 1.0'a doğru yumuşakça iter ("smooth ceiling"). Taşma eşiğine çok yakın kovalar
  neredeyse maksimum skor alır.
- **`etf_urgency = 1 - etf/24`:** Taşmaya 24+ saat varsa 0, 0 saat varsa 1. Yani **yakında
  dolacak** kova yüksek skor alır → erken yakalama.
- **`proximity = 1 - (distance_label-1)/2`:** Mesafe etiketi 1→1.0, 2→0.5, 3→0.0. Yakın
  kovalar hafifçe ödüllendirilir.
- **`traffic_ok = 1 - traffic`:** Trafik azsa yüksek (gitmek için iyi zaman).

Sonuç: 0-1 arası tek bir öncelik skoru. Tüm kovalar bu skora göre sıralanır.

---

## 2.6 KATMAN 3 — Bin Seçimi

### Eşik sabitleri

```python
_RUSH_THR              = 0.70
_MIN_FILL_NORMAL       = 70.0  # normal saatlerde %70+ dolu bin adaya girer
_MIN_FILL_RUSH         = 85.0  # rush saatlerde sadece %85+

ETF_LEAD_TIME          = 3.0   # taşmaya ≤3 sim saat kalan bin → her zaman dahil et
_EMERGENCY_FILL        = 88.0  # %88+ → MIN_DISPATCH şartını bypass et

MIN_DISPATCH = 8           # en az 8 bin seçilemezse (ve acil yoksa) dispatch yapma
```

### `select_bins` — iki geçişli filtre

```python
def select_bins(bins, traffic, depot_lat, depot_lon, max_stops) -> list[_ScoredStop]:
    min_fill = _MIN_FILL_RUSH if traffic > _RUSH_THR else _MIN_FILL_NORMAL

    # İlk geçiş: uygun bin'leri filtrele
    eligible: list[tuple] = []
    for b in bins:
        if b.is_anomaly:
            continue
        etf = _etf_hours(b.fill_pct, b.fill_rate)
        is_emergency       = b.fill_pct >= _EMERGENCY_FILL
        is_etf_urgent      = etf <= ETF_LEAD_TIME
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
```

**İki geçişli tasarım — neden?**
- **1. geçiş (eligibility):** `min_fill` trafiğe göre belirlenir — yoğun saatte %85, normal
  saatte %70. **Üç geçiş kapısı** var: acil (%88+), ETF acil (≤3 saat), ya da eşik üstü. Biri
  bile doğruysa kova aday. **ŞURASI ÖNEMLİ:** ETF kapısı sayesinde henüz %70'e ulaşmamış ama
  hızlı dolan bir kova bile yakalanır.
- **2. geçiş (scoring):** Aday kovalar için yoğunluk hesaplanıp tam skor üretilir. Yoğunluk
  hesabı tüm kova listesini gezdiği için pahalı — bu yüzden sadece elenmiş adaylar için yapılır
  (1. geçiş bir optimizasyon).
- `result.sort(... reverse=True)[:max_stops]` → en yüksek skorlu `max_stops` kova döner.

---

## 2.7 KATMAN 4 — Rota Kurma (NN + Kapasite + 2-opt)

### Nearest-Neighbor sıralama

```python
def _nn_route(scored, depot_lat, depot_lon) -> list[_ScoredStop]:
    remaining = list(scored)
    route: list[_ScoredStop] = []
    cur_lat, cur_lon = depot_lat, depot_lon

    while remaining:
        closest = min(remaining, key=lambda ss: _km(cur_lat, cur_lon, ss.stop.lat, ss.stop.lon))
        route.append(closest)
        cur_lat, cur_lon = closest.stop.lat, closest.stop.lon
        remaining.remove(closest)
    return route
```

**Nearest-Neighbor (En Yakın Komşu) sezgiseli:** Depot'tan başla, her adımda mevcut konuma
**en yakın** kovaya git. Bu, Gezgin Satıcı Problemi (TSP) için hızlı bir başlangıç çözümü
üretir. Optimal değil ama hızlı ve makul. `min(..., key=lambda)` → en yakın kovayı bulur.

### Kapasiteye göre kırpma

```python
def _trim_by_capacity(nn_ordered) -> list[_ScoredStop]:
    result: list[_ScoredStop] = []
    used = 0.0
    for ss in nn_ordered:
        load = (ss.fill_pct / 100.0) * BIN_VOLUME_FRACTION
        if used + load > TRUCK_CAPACITY + 1e-9:
            break
        result.append(ss)
        used += load
    return result
```

**Bu method ne yapıyor?** NN sırasına göre kovaları ekler, **kamyon dolana kadar**. Her kova
doluluğu kadar (`fill_pct/100 * 0.05`) kapasite tüketir. Kapasite aşılınca durur — kalan
kovalar bir sonraki kamyona kalır. `1e-9` kayan nokta toleransı. NN sırasıyla kırpmanın faydası:
yakın kovalar önce yüklenir, uzaktakiler doğal olarak sonraki sefere kalır.

### Ağırlık-duyarlı 2-opt — PROJENİN EN İNCE FİKRİ

```python
def _fuel_aware_dist(stops, dlat, dlon) -> float:
    """
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


def _full_2opt(stops, dlat, dlon) -> list[Stop]:
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
```

**Bu projenin akademik özgünlüğü burada — ŞURASI ÇOK ÖNEMLİ:**

Klasik 2-opt sadece **toplam km'yi** minimize eder. Burada `_fuel_aware_dist` ile **yakıtı**
minimize ediyoruz. Fark ne?
- Kamyon her durakta dolar → ağırlaşır → sonraki bacaklarda daha çok yakıt yakar.
- `w_factor = (i+1)/n` → rota ilerledikçe 0'dan 1'e artan ağırlık faktörü.
- `cost += dist * (1 + 0.8 * w_factor)` → geç bacaklar (ağır kamyon) daha pahalı sayılır.

**Sonuç:** Algoritma "ağır yükle kısa bacak, hafif yükle uzun bacak" düzenini tercih eder.
Yani **uzaktaki kovaya kamyon boşken git, dönüşte yakındakileri topla**. Bu, sadece mesafe
optimize eden klasik yöntemden daha az yakıt harcar.

**2-opt mekaniği:** İki kenarı ters çevirerek (`best[i:j+1][::-1]`) rotayı düzenler. Hiç
iyileşme olmayana kadar (`while improved`) tüm `i, j` çiftlerini dener. `O(n²)` her geçişte
ama kova sayısı küçük olduğu için (≤40) hızlı.

### `build_route` — üç adımı birleştir

```python
def build_route(scored, depot_lat, depot_lon) -> list[Stop]:
    if not scored:
        return []
    nn_ordered = _nn_route(scored, depot_lat, depot_lon)
    trimmed    = _trim_by_capacity(nn_ordered)
    stops      = [ss.stop for ss in trimmed]
    return _full_2opt(stops, depot_lat, depot_lon)
```

Akış: **NN sırala → kapasiteye göre kırp → yakıt-duyarlı 2-opt ile iyileştir.** Üç adımın
sırası önemli: önce kapasiteye sığan seti belirle, sonra o set üzerinde rotayı optimize et.

---

## 2.8 KATMAN 5 — Rota Verimliliği

```python
_MIN_ROUTE_EFFICIENCY = 0.20   # minimum bin/km oranı


def route_efficiency(stops, depot_lat, depot_lon) -> float:
    """Bin sayısı / toplam km. Düşükse bu rota boşa gidiş."""
    dist = _route_dist(stops, depot_lat, depot_lon)
    if dist < 1e-6:
        return float("inf")
    return len(stops) / dist


def _chunk_is_urgent(chunk) -> bool:
    """Grupta acil (%95+) veya ETF kritik bin var mı?"""
    return any(ss.fill_pct >= _EMERGENCY_FILL or ss.etf_h <= ETF_LEAD_TIME for ss in chunk)
```

**`route_efficiency` = kova sayısı / toplam km.** Düşükse (örn. 30 km gidip 2 kova topluyorsa),
bu rota "boşa sefer". `_MIN_ROUTE_EFFICIENCY = 0.20` → km başına en az 0.2 kova olmalı.
`_chunk_is_urgent` → ama grupta **acil** kova varsa, verimsizlik göz ardı edilir (taşmayı
önlemek verimden önemli).

---

## 2.9 KATMAN 6 — Dispatcher (ana karar fonksiyonu)

```python
def dpet_dispatch(bins, active_truck_count, hour, depot_lat, depot_lon,
                  max_fleet, max_stops, min_dispatch=MIN_DISPATCH) -> list[list[Stop]]:
    available_slots = max_fleet - active_truck_count
    if available_slots <= 0:
        return []

    traffic = traffic_score(hour)

    selected = select_bins(bins, traffic, depot_lat, depot_lon,
                           max_stops=max_stops * available_slots)

    has_any_urgent = any(ss.fill_pct >= _EMERGENCY_FILL or ss.etf_h <= ETF_LEAD_TIME
                         for ss in selected)

    if len(selected) < min_dispatch and not has_any_urgent:
        return []

    routes: list[list[Stop]] = []
    for i in range(0, len(selected), max_stops):
        chunk = selected[i:i + max_stops]

        if len(chunk) < min_dispatch and not _chunk_is_urgent(chunk):
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
```

**Bu fonksiyon DPET'in beynidir.** Karar akışını adım adım okuyalım:

1. **`available_slots = max_fleet - active_truck_count`** → boş kamyon slotu var mı? Yoksa
   (`<= 0`) hiç dispatch yapma, boş liste dön. Filo zaten dolu.

2. **`traffic = traffic_score(hour)`** → o saatin trafik durumunu al (Katman 1).

3. **`selected = select_bins(...)`** → skorla ve en iyi kovaları seç (Katman 2-3). `max_stops *
   available_slots` → kaç slot boşsa o kadar fazla kova seç (her slota bir rota dolacak).

4. **`has_any_urgent`** → seçilenler arasında acil kova var mı?

5. **`if len(selected) < min_dispatch and not has_any_urgent: return []` → ŞURASI ÖNEMLİ.**
   Bu **"boşa sefer yapma" kuralı**. En az 8 kova (`MIN_DISPATCH`) toplanamıyorsa **ve** acil
   durum yoksa, kamyon **çıkarma** — biraz daha bekle, kovalar dolsun, sonra toplu git. Bu
   kural, DPET'in sabit rotaya (`fixed`) karşı yakıt/km kazancının ana kaynağıdır. Sabit
   sistem her sabah yarı boş kovalar için bile kamyon çıkarır; DPET beklemeyi öğrenir.

6. **Gruplara böl ve rota kur:** `selected`'ı `max_stops`'luk parçalara böler. Her parça için
   `build_route` ile rota kurar.
   - `if len(chunk) < min_dispatch and not _chunk_is_urgent: break` → parça çok küçük ve
     acil değilse kalan grupları atla.
   - `if eff < _MIN_ROUTE_EFFICIENCY and not _chunk_is_urgent: continue` → verimsiz ve acil
     değilse o rotayı atla (ama sonrakileri dene).
   - `if len(routes) >= available_slots: break` → boş slot kadar rota üretildiyse dur.

7. **`return routes`** → her biri bir kamyona atanacak rotalar listesi.

**Özet:** Bu fonksiyon hem **ne zaman** kamyon çıkacağına (boşa sefer önleme), hem **kaç**
kamyon çıkacağına (slot/verimlilik), hem **hangi rotayla** çıkacağına (build_route) tek elden
karar verir. Simülasyon motoru bunu çağırır (Bölüm 4'te göreceğiz), etrafına da kendi öncelik
katmanlarını sarar.

---

**Sonraki bölüm:** [KOD_DETAY_3 — Çevre Modeli ve Tahmin](KOD_DETAY_3_ENVIRONMENT_PREDICTOR.md)
