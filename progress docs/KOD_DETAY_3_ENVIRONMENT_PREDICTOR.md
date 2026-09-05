# Kod Detaylı Açıklama — Bölüm 3: Çevre Modeli ve Tahmin

> İki modül: **`environment.py`** simülasyona gerçekçi kentsel talep dinamiği katar
> (kovalar günün saatine/bölgeye göre farklı hızda dolar). **`predictor.py`** geçmişten
> dolum hızı öğrenir ve coğrafi zone yönetir.

← Önceki: [Bölüm 2 — DPET Algoritması](KOD_DETAY_2_DPET_ALGORITMA.md)

---

# BÖLÜM 3A — Çevre/Talep Modeli (`environment.py`)

Dışarıya sadece **iki fonksiyon** açar: `assign_district()` ve `effective_fill_rate()`.
İçeride 5 katman var.

## 3A.1 KATMAN 1 — District Tipleri

```python
class DistrictType(str, Enum):
    RESIDENTIAL = "residential"   # konut alanı — akşam piki
    OFFICE      = "office"        # iş merkezi — sabah/öğle piki
    MALL        = "mall"          # AVM — öğleden sonra/akşam piki
    UNIVERSITY  = "university"    # kampüs — ders saatleri piki
    TOURIST     = "tourist"       # turizm — öğle/akşam piki
```

5 bölge tipi. Her birinin farklı bir **günlük çöp üretim deseni** var. Bu, gerçek hayatın
temel gözlemi: ofis bölgesi sabah dolar (insanlar işe gelir), konut bölgesi akşam dolar
(aile evdedir). Bu çeşitlilik, DPET'in adaptif davranışını test etmek için kritik.

## 3A.2 KATMAN 2 — Saatlik Profiller

```python
HOURLY_PROFILES: dict[DistrictType, list[float]] = {

    # Konut: gece sakin, sabah kahvaltı, akşam yoğun (aile evde)
    DistrictType.RESIDENTIAL: [
        0.2, 0.2, 0.2, 0.2, 0.2, 0.3,   # 00-05  gece
        0.6, 0.9, 0.8, 0.6, 0.5, 0.5,   # 06-11  sabah
        0.6, 0.6, 0.5, 0.6, 0.8, 1.2,   # 12-17  öğlen / dönüş
        1.8, 2.0, 1.7, 1.3, 0.8, 0.4,   # 18-23  akşam piki
    ],

    # Ofis: gece kapalı, sabah-öğle arası yoğun, akşam boş
    DistrictType.OFFICE: [
        0.1, 0.1, 0.1, 0.1, 0.1, 0.2,   # 00-05  kapalı
        0.4, 0.9, 1.8, 1.9, 1.7, 1.4,   # 06-11  sabah piki
        1.6, 1.5, 1.3, 1.1, 0.7, 0.3,   # 12-17  öğleden sonra düşüş
        0.2, 0.1, 0.1, 0.1, 0.1, 0.1,   # 18-23  gece
    ],
    # ... MALL, UNIVERSITY, TOURIST benzer şekilde ...
}


def hourly_multiplier(district: DistrictType, hour: int) -> float:
    """Belirtilen district ve saat için çarpanı döndür."""
    return HOURLY_PROFILES[district][hour % 24]
```

**Bu yapı ne anlatıyor?** Her district için **24 elemanlı bir dizi** — her saat için bir
dolum çarpanı. `1.0` ortalama hız, `2.0` iki kat hızlı, `0.1` neredeyse durmuş demek.

**Önemli örnekler:**
- **Konut** (`RESIDENTIAL`): saat 19'da `2.0` (akşam piki — aile evde, yemek çöpü). Gece `0.2`.
- **Ofis** (`OFFICE`): saat 9'da `1.9` (sabah yoğun). Akşam ve gece `0.1` (kapalı).

`hourly_multiplier` → `hour % 24` ile saati güvenli aralığa sokar (24+ saat gelse bile çalışır).
Bu değerler "gerçekçi kentsel gözlemlere dayanır" — projeye gerçeklik katan kısım.

## 3A.3 KATMAN 3 — Gürültü Modeli

```python
_NOISE_STD = 0.10   # standart sapma: ±%10


def apply_noise(value: float) -> float:
    """Değere ±%10 Gaussian gürültü ekle; sonuç negatif olamaz."""
    noise_factor = 1.0 + random.gauss(0.0, _NOISE_STD)
    return max(0.0, value * noise_factor)
```

**Neden gürültü?** Gerçek hayat deterministik değil. Aynı saatte her gün tam olarak aynı
miktarda çöp üretilmez. `random.gauss(0, 0.10)` → ortalaması 0, standart sapması 0.10 olan
**Gaussian (normal) dağılım**. Çoğu zaman ±%10 içinde, nadiren daha fazla sapma. `max(0.0, ...)`
→ gürültü değeri negatife düşürmesin (negatif dolma hızı anlamsız). Bu, her simülasyon
çalışmasını biraz farklı ve gerçekçi yapar.

## 3A.4 KATMAN 4 — Event (Olay) Sistemi

Konser, maç, festival gibi **geçici talep patlamaları**.

```python
@dataclass
class Event:
    event_id:            str
    event_type:          str               # "concert", "match", "festival"…
    start_sim_s:         float
    end_sim_s:           float
    affected_districts:  list[DistrictType]
    multiplier:          float             # dolum hızı çarpanı (örn. 2.5)
    description:         str = ""

    def is_active(self, sim_s: float) -> bool:
        return self.start_sim_s <= sim_s <= self.end_sim_s

    def affects(self, district: DistrictType) -> bool:
        return district in self.affected_districts
```

Bir `Event`'in başlangıç/bitiş zamanı, etkilediği bölgeler ve bir çarpanı var. `is_active`
→ verilen sim zamanında aktif mi? `affects` → belirli bir bölgeyi etkiliyor mu?

### Event şablonları

```python
_EVENT_TEMPLATES: list[tuple] = [
    ("concert",  [DistrictType.TOURIST, DistrictType.RESIDENTIAL], (1.8, 3.0), 4 * 3_600),
    ("match",    [DistrictType.TOURIST, DistrictType.MALL],        (2.0, 3.5), 3 * 3_600),
    ("festival", [DistrictType.TOURIST, DistrictType.MALL, DistrictType.RESIDENTIAL], (1.5, 2.5), 8 * 3_600),
    ("sale",     [DistrictType.MALL],                              (1.5, 2.0), 6 * 3_600),
    ("weekend",  list(DistrictType),                               (1.2, 1.6), 48 * 3_600),
]

_EVENT_MIN_GAP_S = 12 * 3_600
_EVENT_MAX_GAP_S = 48 * 3_600
```

Her şablon: (tip, etkilenen bölgeler, çarpan **aralığı**, süre saniye). Örnek: bir konser
turist+konut bölgelerini etkiler, çarpan 1.8-3.0 arası rastgele, 4 saat sürer. Eventler arası
12-48 saat boşluk olur.

### EventManager — olayları yöneten sınıf

```python
class EventManager:
    def __init__(self) -> None:
        self._events: list[Event] = []
        self._counter: int = 0
        self._next_spawn_s: float = _EVENT_MIN_GAP_S

    def tick(self, sim_s: float) -> Event | None:
        self._cleanup(sim_s)
        if sim_s >= self._next_spawn_s:
            return self._spawn(sim_s)
        return None

    def active(self, sim_s: float) -> list[Event]:
        return [e for e in self._events if e.is_active(sim_s)]

    def _spawn(self, sim_s: float) -> Event:
        self._counter += 1
        etype, districts, mult_range, duration = random.choice(_EVENT_TEMPLATES)
        mult = round(random.uniform(*mult_range), 2)
        ev = Event(
            event_id           = f"EVT_{self._counter:04d}",
            event_type         = etype,
            start_sim_s        = sim_s,
            end_sim_s          = sim_s + duration,
            affected_districts = list(districts),
            multiplier         = mult,
            description        = f"{etype} (x{mult})",
        )
        self._events.append(ev)
        self._next_spawn_s = sim_s + random.uniform(_EVENT_MIN_GAP_S, _EVENT_MAX_GAP_S)
        return ev

    def _cleanup(self, sim_s: float) -> None:
        self._events = [e for e in self._events if e.end_sim_s >= sim_s]
```

**Her method ne yapıyor:**
- `tick(sim_s)` → motorun her tick'inde çağrılır. Önce süresi dolmuş eventleri temizler, sonra
  `_next_spawn_s` geldiyse **yeni event üretir**. Yeni event varsa döner (motor anomali loguna yazar).
- `active(sim_s)` → o anda aktif tüm eventleri döner. `effective_fill_rate` bunu kullanır.
- `_spawn` → rastgele bir şablon seçer (`random.choice`), çarpanı aralıktan rastgele belirler,
  `EVT_0001` gibi kimlik verir. Bir sonraki spawn zamanını da rastgele ayarlar.
- `_cleanup` → bitmiş eventleri listeden çıkarır (bellek kontrolü).

## 3A.5 KATMAN 5 — Public API

### `assign_district` — region string'inden bölge tipi çıkar

```python
_DISTRICT_DISTRIBUTION: list[tuple[DistrictType, float]] = [
    (DistrictType.RESIDENTIAL, 0.40),
    (DistrictType.OFFICE,      0.20),
    (DistrictType.MALL,        0.15),
    (DistrictType.UNIVERSITY,  0.15),
    (DistrictType.TOURIST,     0.10),
]

_REGION_KEYWORDS: dict[DistrictType, list[str]] = {
    DistrictType.UNIVERSITY: ["univ", "college", "campus", "tech"],
    DistrictType.MALL:       ["mall", "shop", "centre", "center", "retail"],
    DistrictType.TOURIST:    ["hotel", "tourist", "museum", "temple", "temple bar"],
    DistrictType.OFFICE:     ["office", "business", "corp", "dock", "ifsc"],
}


def assign_district(region: str | None = None) -> DistrictType:
    if region:
        r = region.lower()
        for district, keywords in _REGION_KEYWORDS.items():
            if any(kw in r for kw in keywords):
                return district

    # Ağırlıklı rastgele seçim
    rand = random.random()
    cumulative = 0.0
    for district, prob in _DISTRICT_DISTRIBUTION:
        cumulative += prob
        if rand <= cumulative:
            return district
    return DistrictType.RESIDENTIAL
```

**Bu method ne yapıyor?** Bir kovanın `region` metnine (örn. "Trinity College Dublin") bakarak
hangi bölge tipinde olduğunu tahmin eder.
- **Önce anahtar kelime araması:** region "college" içeriyorsa → `UNIVERSITY`. `any(kw in r ...)`
  ile herhangi bir anahtar kelime eşleşirse o tipi döner.
- **Eşleşme yoksa → ağırlıklı rastgele atama.** Dublin'in gerçekçi dağılımına göre (%40 konut,
  %20 ofis, ...) rastgele bir tip seçer. `cumulative` (kümülatif olasılık) tekniği: 0-1 arası
  rastgele sayı hangi aralığa düşerse o bölge seçilir.

### `effective_fill_rate` — EN ÖNEMLİ FONKSİYON

```python
def effective_fill_rate(base_rate, district, hour, events) -> float:
    h_mult = hourly_multiplier(district, hour)

    # Aynı anda birden fazla event olabilir — en yüksek çarpanı al
    e_mult = 1.0
    for ev in events:
        if ev.affects(district):
            e_mult = max(e_mult, ev.multiplier)

    rate = base_rate * h_mult * e_mult
    return apply_noise(rate)
```

**Bu fonksiyon, bir kovanın o tick'teki gerçek dolma hızını hesaplar.** Simülasyon motorunun
`_job_fill` fonksiyonu her kova için bunu çağırır.

**Formül — ŞURASI ÖNEMLİ:**
```
gerçek_hız = temel_hız × saat_çarpanı × event_çarpanı × gürültü
```
- `base_rate` → kovanın sabit temel hızı (etikete göre atanmış: A=hızlı, C=yavaş).
- `h_mult` → o saatteki bölgesel çarpan (ofis sabah 1.9, gece 0.1).
- `e_mult` → aktif event varsa çarpan. **Birden fazla event varsa `max` alınır** (en güçlü
  olay baskındır, çarpanlar toplanmaz).
- `apply_noise` → son olarak ±%10 gürültü.

Bu dört faktörün çarpımı, çok katmanlı gerçekçi bir talep modeli oluşturur. Aynı kova,
sabah ofis saatinde hızla, gece yavaşça dolar; bir konser olursa fırlar.

---

# BÖLÜM 3B — Tahmin ve Zone Yönetimi (`predictor.py`)

İki sorumluluğu var: **(1) K-means coğrafi zone ataması**, **(2) geçmişten dolum hızı öğrenme**.

## 3B.1 Sabitler ve Kurulum

```python
N_ZONES           = 12    # K-means zone sayısı (mikro-zone: daha küçük, daha yoğun)
KMEANS_ITERATIONS = 25    # Lloyd iterasyon sayısı
MAX_CYCLES        = 8     # bin başına rolling window büyüklüğü
LOOKAHEAD_H       = 7.0   # sim saat — bu süre içinde dolacak bin'ler "zone-ready"
MIN_ZONE_BINS     = 6     # zone dispatch tetiklemek için minimum bin sayısı


class FillPredictor:
    def __init__(self) -> None:
        self._cycles:       dict[str, list[float]]   = {}   # bin_id → dolum süreleri
        self._last_emptied: dict[str, float]          = {}   # bin_id → son EMPTIED zamanı
        self._bin_zone:     dict[str, int]            = {}   # bin_id → zone_id
        self._zone_bins:    dict[int, list[str]]      = defaultdict(list)
        self._centroids:    list[tuple[float, float]] = []
```

İç veri yapıları:
- `_cycles` → her kova için gözlenen dolum döngüsü sürelerinin listesi (öğrenme verisi).
- `_last_emptied` → her kovanın son ne zaman boşaltıldığı (döngü başlangıcı).
- `_bin_zone` / `_zone_bins` → kova↔zone eşlemeleri (iki yönlü).
- `_centroids` → her zone'un coğrafi merkezi.

## 3B.2 K-means++ ile Zone Ataması

```python
def assign_zones(self, bins: list, n_zones: int = N_ZONES) -> None:
    if not bins:
        return

    points = [(b.bin_id, b.lat, b.lon) for b in bins]
    n = min(n_zones, len(points))

    # K-means++ başlangıç centroid'leri
    centroids = [random.choice(points)[1:]]
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
        clusters = defaultdict(list)
        for bid, lat, lon in points:
            nearest = min(range(len(centroids)),
                          key=lambda i: _geo_dist(lat, lon, centroids[i][0], centroids[i][1]))
            clusters[nearest].append((bid, lat, lon))

        new_centroids = []
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
        zone = min(range(len(centroids)),
                   key=lambda i: _geo_dist(lat, lon, centroids[i][0], centroids[i][1]))
        self._bin_zone[bid] = zone
        self._zone_bins[zone].append(bid)
```

**Bu method ne yapıyor?** Tüm kovaları coğrafi yakınlığa göre 12 "zone"a böler. Startup'ta
**bir kez** çalışır (kova konumları değişmez).

**İki aşama — ŞURASI ÖNEMLİ:**
1. **K-means++ başlangıcı:** Klasik K-means rastgele başlangıç merkezleri seçer, kötü kümeler
   oluşabilir. K-means++ ise merkezleri **birbirinden uzak** seçer: her yeni merkez, mevcut
   merkezlere uzaklığı orantısında olasılıkla seçilir (`r = random() * total` + kümülatif).
   Bu, daha dengeli ve hızlı yakınsayan kümeler verir.
2. **Lloyd iterasyonları (25 kez):** Klasik K-means döngüsü:
   - Her kovayı en yakın merkeze ata (`nearest = min(...)`).
   - Her kümenin yeni merkezini, üyelerinin ortalama konumu olarak hesapla (`sum/len`).
   - 25 kez tekrarla → merkezler oturur.
3. **Final atama:** Son merkezlere göre her kovanın zone'unu kaydet (iki yönlü: `_bin_zone`
   ve `_zone_bins`).

**Zone'ların amacı:** DPET dispatch'i kovaları zone bazında gruplar. Aynı zone'daki kovalar
coğrafi olarak yakındır → tek kamyonla verimli toplanır.

## 3B.3 Geçmişten Öğrenme

```python
def record_event(self, event: str, bin_id: str, sim_s: float) -> None:
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
```

**Bu method ne yapıyor?** Simülasyon motorundan gelen olayları (sadece `algo` dünyası) işleyerek
**her kovanın gerçek dolum süresini öğrenir**.
- `EMPTIED` → kova boşaltıldı, döngü başlangıç zamanını kaydet.
- `OVERFLOW` → kova taştı. `cycle_s = şimdi - son_boşaltma` → bir **tam dolum döngüsü süresi**.
  Bu süreyi listeye ekler.
- **`if len(cycles) > MAX_CYCLES: cycles.pop(0)` → ŞURASI ÖNEMLİ.** Sadece **son 8 döngü**
  tutulur (rolling window / kayan pencere). Eski veri atılır. Böylece kovanın **güncel**
  davranışını yansıtır — talep zamanla değişirse model uyum sağlar.

## 3B.4 Tahmin Fonksiyonları

```python
def predicted_fill_rate_h(self, bin_id: str, fallback_rate: float) -> float:
    cycles = self._cycles.get(bin_id, [])
    if len(cycles) < 2:
        return fallback_rate
    avg_s = sum(cycles) / len(cycles)
    return 100.0 / (avg_s / 3600.0)


def predicted_etf_h(self, bin_id, fill_pct, fallback_rate) -> float:
    rate = self.predicted_fill_rate_h(bin_id, fallback_rate)
    if rate <= 0:
        return float("inf")
    return max(0.0, (100.0 - fill_pct) / rate)
```

- **`predicted_fill_rate_h`:** Öğrenilen döngülerden ortalama dolma hızını hesaplar.
  - `if len(cycles) < 2: return fallback_rate` → **2'den az gözlem varsa**, henüz güvenilir
    öğrenme yok → konfigüre edilmiş statik `fill_rate`'e düş. Bu "soğuk başlangıç" çözümü:
    simülasyon başında statik değer, ilerledikçe gözleme dayalı değer kullanılır.
  - `100.0 / (avg_s / 3600.0)` → ortalama döngü süresinden %/saat hıza çevirir (100% dolması
    `avg_s` saniye sürüyorsa, saatlik hız budur).
- **`predicted_etf_h`:** Öğrenilen hızı kullanarak taşmaya kalan saati tahmin eder. DPET'in
  dispatch katmanları bu tahmini kullanır (statik ETF yerine öğrenilmiş ETF).

## 3B.5 Zone Sorguları (dispatch katmanlarını besler)

```python
def urgent_zone_bins(self, available, etf_threshold_h, min_bins) -> dict[int, list]:
    zone_urgent = defaultdict(list)
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
```

**Tier-1 (Acil zone) için.** ETF'i eşiğin (örn. 2 saat) altındaki kovaları **zone bazında**
gruplar. Sadece `min_bins`'ten fazla kova içeren zone'ları döner — tek-iki kova için kamyon
çıkarmamak adına. Taşma önlemenin ana mekanizması: bir zone'da çok sayıda kova yakında dolacaksa,
oraya kamyon gönder.

```python
def coverage_zone_bins(self, available, zone_id, min_fill) -> list:
    return [
        b for bid, b in available.items()
        if not b.is_anomaly
        and b.fill_pct >= min_fill
        and self._bin_zone.get(bid) == zone_id
    ]
```

**Tier-2 (Coverage rotation) için.** Belirli bir zone'daki `min_fill` üstü kovaları döner.
"Düzenli ziyaret" sırasında o zone'da ne toplanacağını belirler.

```python
def adaptive_coverage_interval_s(self, zone_id, available, base_interval_s) -> float:
    zone_bin_ids = self._zone_bins.get(zone_id, [])
    etfs = []
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
```

**Bu method ne yapıyor? — ŞURASI AKILLICA.** Her zone'un **ne sıklıkla** ziyaret edileceğini
o zone'un dolum hızına göre **adaptif** ayarlar.
- Zone'daki tüm kovaların ETF'lerini toplar, **medyanını** alır (aykırı değerlere dayanıklı).
- `ratio = median_etf / base` → zone hızlı doluyorsa medyan ETF küçük → ratio küçük → **kısa
  interval** (sık ziyaret). Yavaş doluyorsa tersi.
- `max(0.25, min(3.0, ...))` → ratio'yu [0.25, 3.0] aralığına sıkıştırır (çok aşırı değerleri
  engeller). Yani bir zone en sık baz aralığın 1/4'ünde, en seyrek 3 katında ziyaret edilir.

**Sonuç:** Hızlı dolan bölgelere sık, yavaş bölgelere seyrek gidilir → yakıt tasarrufu +
taşma önleme dengesi.

## 3B.6 Reset — öğrenmeyi sıfırla, zone'ları koru

```python
def reset(self) -> None:
    self._cycles.clear()
    self._last_emptied.clear()
```

**Önemli ayrıntı:** Simülasyon sıfırlandığında **sadece öğrenilen veri** silinir. Zone
atamaları (`_bin_zone`, `_centroids`) **korunur** — çünkü kova konumları değişmedi, K-means'i
tekrar çalıştırmak (pahalı işlem) gereksiz. İyi bir performans optimizasyonu.

---

**Sonraki bölüm:** [KOD_DETAY_4 — Simülasyon Motoru](KOD_DETAY_4_SIMULASYON_MOTORU.md)
