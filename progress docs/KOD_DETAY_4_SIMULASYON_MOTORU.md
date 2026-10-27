# Kod Detaylı Açıklama — Bölüm 4: Simülasyon Motoru (`simulation_engine.py`)

> **1233 satır — projenin en büyük ve merkezi dosyası.** Tüm modülleri (`dpet`,
> `environment`, `predictor`) orkestre eder ve "iki paralel dünya" fikrini hayata
> geçirir. Bu doküman dosyayı **alan alan (region region)**, kritik methodları
> **satır satır**, ve her parçanın **bağlandığı yerleri** (kim çağırır / kimi çağırır)
> göstererek anlatır.

← Önceki: [Bölüm 3 — Çevre ve Tahmin](KOD_DETAY_3_ENVIRONMENT_PREDICTOR.md)

---

## 0. Kuşbakışı — Motor Nerede Duruyor?

```
                          ┌─────────────────────────────────────────────┐
   ESP32 (gerçek sensör)  │              FastAPI Backend                 │
        │ POST            │                                             │
        ▼                 │   main.py ──► routers/simulation.py         │
   bins_service.py ───────┼──►  engine.inject_sensor_reading()          │
   (log_state_change)     │                  │                          │
                          │                  ▼                          │
                          │        ┌──────────────────────┐             │
   React Frontend  ◄──────┼────────┤  SimulationEngine      │            │
   (her 1-3 sn poll)      │ GET    │  (singleton `engine`)  │            │
                          │        │                        │            │
                          │        │  _loop() her 0.2 sn:   │            │
                          │        │   ├ _job_events ───────┼─► environment.EventManager
                          │        │   ├ _job_fill ─────────┼─► environment.effective_fill_rate
                          │        │   ├ _job_dispatch_algo ┼─► dpet.dpet_dispatch + predictor
                          │        │   ├ _job_dispatch_fixed │            │
                          │        │   ├ _job_anomaly ───────┼─► services.anomaly_service (DB)
                          │        │   ├ _heal_anomalies     │            │
                          │        │   └ _advance_trucks     │            │
                          │        └──────────────────────┘             │
                          └─────────────────────────────────────────────┘
```

**Motorun rolü:** Kendisi algoritma/talep modeli içermez — bu işleri 3 modüle devreder,
sonuçları **iki dünyada** (algo vs fixed) paralel işletip KPI'larını karşılaştırır.

| Bağımlılık | Ne sağlar | Nerede kullanılır |
|------------|-----------|-------------------|
| `dpet.py` | Dispatch algoritması (rota seçimi/kurma) | `_job_dispatch_algo` |
| `environment.py` | Talep modeli (saatlik/event/gürültü) + event üretimi | `_job_fill`, `_job_events`, `load_bins` |
| `predictor.py` | K-means zone + öğrenilmiş ETF | `_job_dispatch_algo`, `_append_history` |
| `services/anomaly_service.py` | Anomalinin DB'ye yazımı | `_log_anomaly_db` |
| `services/bins_service.py` | **Motoru çağıran taraf** (gerçek sensör) | `inject_sensor_reading` buradan tetiklenir |
| `routers/simulation.py` | Motoru web'e açan kapak | `start/stop/reset/snapshot` |

---

## 0.1 "İki Paralel Dünya" — Projenin Kalbi

```
                 AYNI KOVALAR · AYNI DOLUM VERİSİ · AYNI ANOMALİLER
                                      │
            ┌─────────────────────────┴─────────────────────────┐
            ▼                                                     ▼
   ┌──────────────────┐                              ┌──────────────────┐
   │   ALGO DÜNYASI    │                              │   FIXED DÜNYASI   │
   │  (DPET dinamik)   │                              │  (sabit rotalar)  │
   ├──────────────────┤                              ├──────────────────┤
   │ algo_bins         │                              │ fixed_bins        │
   │ algo_trucks       │                              │ fixed_trucks      │
   │ algo_kpis         │                              │ fixed_kpis        │
   │ _job_dispatch_algo│                              │ _job_dispatch_fixed│
   │ predictor öğrenir │                              │ öğrenmez          │
   └────────┬─────────┘                              └─────────┬────────┘
            └──────────────────┬──────────────────────────────┘
                               ▼
                  kpis_snapshot → savings = fixed − algo
                  (DPET'in km/yakıt/CO₂/taşma kazancı)
```

İki dünya **birebir aynı koşullara** maruz kalır; tek fark toplama stratejisidir. Bu, "DPET
sabit sisteme göre ne kadar tasarruf sağlıyor?" sorusunun kontrollü-deney cevabıdır.

---

## ALAN HARİTASI

| # | Alan | Method'lar |
|---|------|-----------|
| A | Modül başı + Sabitler | import, depo/yakıt/eşik/tier parametreleri |
| B | Veri Sınıfları | `BinState`, `TruckRoute` |
| C | Geometri/Rota Yardımcıları | `_haversine_km`, `_nearest_neighbor`, `_two_opt_route`, `_weighted_fuel`, `_remaining_route_km`, `_insertion_km`, `_dist_to_segment_km` |
| D | Snapshot Yardımcıları | `_bin_to_dict`, `_truck_to_dict` |
| E | Engine Kurulumu | `__init__`, `_zero_kpis`, `virtual_clock` |
| F | Veri Yükleme | `load_bins`, `_compute_depot`, `_precompute_fixed_routes` |
| G | Kontrol | `start`, `stop`, `reset` |
| H | Ana Döngü | `_loop` |
| I | Fill Job | `_job_fill` |
| J | Sensör Enjeksiyonu | `inject_sensor_reading`, `_push_sensor_anomaly` |
| K | Rota Genişletme | `_corridor_bins`, `_try_extend_truck` |
| L | Dispatch Algo (DPET) | `_job_dispatch_algo` (4 katman) |
| M | Dispatch Fixed | `_job_dispatch_fixed`, `_dispatch_next_fixed_route` |
| N | Kamyon Oluşturma | `_create_truck` |
| O | Kamyon İlerlemesi | `_advance_trucks`, `_step_truck`, `_active_stop_bin_ids` |
| P | Event/History/Anomaly | `_job_events`, `_append_history`, `_job_anomaly`, `_heal_anomalies`, `_log_anomaly_db` |
| Q | Snapshot'lar | `state_snapshot`, `kpis_snapshot` |

---

# ALAN A — Modül Başı ve Sabitler

```python
from .dpet import BIN_VOLUME_FRACTION, TRUCK_CAPACITY, Stop, dpet_dispatch
from .environment import DistrictType, Event, EventManager, assign_district, effective_fill_rate
from .predictor import FillPredictor
```

**🔗 Bağlantı:** Bu 3 import projenin mimarisini özetler. Motor karar vermez; bu modülleri çağırır.

### Depo + fiziksel katsayılar
```python
_DEFAULT_DEPOT_LAT, _DEFAULT_DEPOT_LON = 53.3498, -6.2603   # Dublin merkez
DEPOT_NORTH_OFFSET = 0.005          # ~550 m kuzey offset
CO2_PER_KM        = 0.28            # kg CO2 / km
FUEL_PER_KM       = 0.35            # L/km (boş kamyon)
WEIGHT_MULTIPLIER = 0.8             # tam dolu kamyon %80 fazla yakar
TRUCK_SPEED_KMH   = 30.0            # şehir içi ortalama
SERVICE_SIM_MIN   = 5               # durak başına servis (sim-dakika)
```
- `CO2_PER_KM`, `FUEL_PER_KM` → KPI çarpanları (`_weighted_fuel`, `_create_truck`'ta kullanılır).
- `TRUCK_SPEED_KMH` → bir bacağın süresini hesaplar: `süre = mesafe/hız` (`_step_truck`, `_create_truck`).

### Dolum hızı aralıkları + eşikler
```python
FILL_RATE_RANGES = {"A": (12.0,16.0), "B": (4.0,8.0), "C": (0.5,1.5)}  # %/sim-saat
FULL_THRESHOLD     = 50.0
CRITICAL_THRESHOLD = 85.0
```
**A hızlı / C yavaş dolar** → DPET'in ETF avantajını (A) ve sabit rotanın boşa seferini (C)
belirginleştirmek için kasıtlı. **🔗 Kullanım:** `load_bins` (hız atama), `BinState.refresh_status` (eşikler).

### Maliyet + zamanlayıcılar
```python
DISPATCH_COST_TL = 2_000   # sefer başına sabit maliyet
FUEL_PRICE_TL    = 45      # TL/L
FILL_JOB_INTERVAL_S      = 3_600   # dolum her 1 sim-saat
DISPATCH_ALGO_INTERVAL_S = 3_600   # DPET her 1 sim-saat
ANOMALY_MIN_INTERVAL_S, ANOMALY_MAX_INTERVAL_S = 300, 1_200
```
`DISPATCH_COST_TL=2000` → her sefer pahalı; "az ama dolu sefer" stratejisini ödüllendirir.

### Dispatch katman parametreleri
```python
ALGO_MAX_STOPS=40; FIXED_ROUTE_SIZE=20; FIXED_DISPATCH_HOUR=6; MAX_FLEET_SIZE=12
EXTENSION_FILL_THRESHOLD=90.0; MAX_DETOUR_RATIO=0.30; OPPORTUNISTIC_FILL_THRESHOLD=55.0
FALLBACK_EMERGENCY_FILL=90.0
URGENT_ZONE_ETF_H=2.0; URGENT_ZONE_MIN_BINS=4          # Tier-1
COVERAGE_INTERVAL_S=20*3600; COVERAGE_MIN_FILL=50.0    # Tier-2
CORRIDOR_RADIUS_KM=0.65; CORRIDOR_MIN_FILL=70.0        # koridor
AGING_THRESHOLD_S=4*3600; AGING_MIN_BINS=3             # Tier-0
```
**🔗 Bağlantı:** Hepsi ALAN L'de (`_job_dispatch_algo`) ve ALAN K'da kullanılır.

### Sensör sabitleri (ESP32 firmware ile eşleşmeli)
```python
SENSOR_BIN_HEIGHT_CM = 100.0   # ESP32-Sensor.ino BIN_HEIGHT_CM ile AYNI
SENSOR_OFFSET_CM     = 3.0     # ESP32-Sensor.ino SENSOR_OFFSET_CM ile AYNI
SENSOR_ENUM_FILL_PCT = {"EMPTY":0.0, "FULL":75.0, "CRITICAL_FULL":95.0}
SPEED_OPTIONS = {"1x":1, "60x":60, "3600x":3600, "86400x":86400}
```
**🔗 Kritik bağlantı:** Bu iki sabit firmware ile **birebir** olmalı — gerçek sensör verisi
aynı geometriyle yüzdeye çevrilir (`inject_sensor_reading`, ALAN J).

---

# ALAN B — Veri Sınıfları

### `BinState` — bir kovanın canlı durumu
```python
@dataclass
class BinState:
    bin_id: str; lat: float; lon: float; region: str
    fill_label: str = "C"; distance_label: int = 2
    district_type: DistrictType = DistrictType.RESIDENTIAL
    fill_rate: float = 1.0; fill_pct: float = 0.0; status: str = "EMPTY"
    is_anomaly: bool = False; anomaly_end_sim_s: float = 0.0
    overflow_start_s: float = -1.0      # ilk %100 anı; -1 = taşmadı (aging için)
    last_emptied_sim_s: float = -1.0    # son boşaltım; predictor + UI
```
Önemli alanlar: `fill_pct` (anlık doluluk), `overflow_start_s` (Tier-0 aging hesabı),
`last_emptied_sim_s` (predictor öğrenmesi + UI gösterimi).

```python
    def refresh_status(self) -> None:
        if self.is_anomaly: return
        if self.fill_pct >= CRITICAL_THRESHOLD: self.status = "CRITICAL_FULL"
        elif self.fill_pct >= FULL_THRESHOLD:   self.status = "FULL"
        else:                                   self.status = "EMPTY"
```
`fill_pct → status` dönüşümü. **`if self.is_anomaly: return`** → anomali durumu doluluğun üstüne yazar, dokunma.
**🔗 Çağıranlar:** `_job_fill`, `inject_sensor_reading`, `_job_anomaly`, `_heal_anomalies`.

```python
    def empty(self, sim_s: float = -1.0) -> None:
        self.last_emptied_sim_s = sim_s; self.fill_pct = 0.0
        self.is_anomaly = False; self.overflow_start_s = -1.0; self.status = "EMPTY"
```
Boşaltıldığında tüm durumu sıfırlar (taşma sayacı dahil).
**🔗 Çağıranlar:** `_step_truck` (kamyon boşalttı), `inject_sensor_reading` (gerçek boşalma).

### `TruckRoute` — bir kamyonun canlı durumu
```python
@dataclass
class TruckRoute:
    truck_id: int; route_type: str
    stops: list = field(default_factory=list)
    full_latlons: list = field(default_factory=list)   # tüm rota (UI soluk çizgi)
    current_stop_idx: int = 0
    lat/lon = 0.0; from_lat/lon = 0.0; to_lat/lon = 0.0  # anlık + bacak uçları
    leg_start_sim_s/leg_end_sim_s/service_end_sim_s = 0.0
    status: str = "en_route"        # en_route / servicing / returning / done
    at_bin/to_bin: str|None = None; progress: float = 0.0; capacity_used: float = 0.0
```
**`field(default_factory=list)`** → her kamyona ayrı liste (mutable default tuzağı önleme).
**🔗 Üretilir:** `_create_truck`. **İşlenir:** `_step_truck`, `_advance_trucks`. **Serileştirilir:** `_truck_to_dict`.

---

# ALAN C — Geometri/Rota Yardımcıları (saf fonksiyonlar)

`_haversine_km`, `_nearest_neighbor`, `_two_opt_route` → dpet'teki muadilleriyle aynı mantık
(km mesafesi, NN sıralama, 2-opt). Üç tanesi motora özel:

### `_weighted_fuel` — KPI'ın temeli
```python
def _weighted_fuel(stops, depot_lat, depot_lon) -> tuple[float, float]:
    n = len(stops); total_km = total_fuel = 0.0
    prev_lat, prev_lon = depot_lat, depot_lon
    for i, stop in enumerate(stops):
        dist     = _haversine_km(prev_lat, prev_lon, stop.lat, stop.lon)
        w_factor = i / max(n, 1)                       # 0→1 doldukça
        fuel_km  = FUEL_PER_KM * (1 + WEIGHT_MULTIPLIER * w_factor)
        total_km += dist; total_fuel += dist * fuel_km
        prev_lat, prev_lon = stop.lat, stop.lon
    dist_ret = _haversine_km(prev_lat, prev_lon, depot_lat, depot_lon)
    total_km += dist_ret
    total_fuel += dist_ret * FUEL_PER_KM * (1 + WEIGHT_MULTIPLIER)   # dönüş = tam dolu
    return total_km, total_fuel
```
Depot→duraklar→depot için **ağırlık-duyarlı** km ve yakıt. Kamyon doldukça `w_factor` artar.
**🔗 Çağıran:** `_create_truck` (KPI: distance_km, fuel_l).

### `_remaining_route_km` — kalan rota mesafesi
```python
def _remaining_route_km(truck, depot_lat, depot_lon) -> float:
    if truck.status == "returning":
        return _haversine_km(truck.lat, truck.lon, depot_lat, depot_lon)
    after_idx = truck.current_stop_idx + (1 if truck.status == "servicing" else 0)
    remaining = truck.stops[after_idx:]
    ...  # cur→remaining[0]→...→remaining[-1]→depot toplamı
```
Kamyonun **kalan** yolu. **🔗 Çağıran:** `_try_extend_truck` (sapma oranı = ek_km / kalan_km).

### `_insertion_km` — en ucuz ekleme noktası
```python
def _insertion_km(truck, new_stop, depot_lat, depot_lon) -> tuple[float, int]:
    if   truck.status=="servicing": after_idx = cur+1;       prev = stops[cur]
    elif truck.status=="returning": after_idx = len(stops);  prev = anlık konum
    else: # en_route — mevcut hedef değiştirilemez
        after_idx = cur+1; prev = stops[cur]
    for i, stop in enumerate(remaining):
        extra = (km(prev,new) + km(new,stop) - km(prev,stop))   # araya sokma maliyeti
        if extra < best_extra: best_extra, best_pos = extra, after_idx+i
    # son durak ardına (depot öncesi) ekleme de denenir
    return best_extra, best_pos
```
"Yeni kovayı rotaya nereye eklersem en az ek km?" **`else: en_route — mevcut hedef değiştirilemez`**
= kamyon giderken yön değişmez (gerçekçilik). **🔗 Çağıran:** `_try_extend_truck`.

### `_dist_to_segment_km` — nokta-segment mesafesi
```python
def _dist_to_segment_km(p, a, b) -> float:
    # flat-earth: lat/lon → km, P'nin A→B doğru parçasına dik mesafesi
    t = max(0.0, min(1.0, projeksiyon))   # [0,1] clamp
    ...
```
Kovanın kamyonun **rota bacağına** ne kadar yakın olduğunu ölçer.
**🔗 Çağıran:** `_corridor_bins` (yol üstü kova tespiti).

---

# ALAN D — Snapshot Yardımcıları

### `_bin_to_dict` — kovayı frontend JSON'una çevir
```python
def _bin_to_dict(b, sim_s, sim_epoch) -> dict:
    if b.fill_pct >= 100.0 or b.is_anomaly:
        estimated_full_iso = None
    elif b.fill_rate > 0:
        etf_h = (100.0 - b.fill_pct) / b.fill_rate
        estimated_full_iso = (sim_epoch + timedelta(seconds=sim_s)
                              + timedelta(hours=etf_h)).isoformat()
    else: estimated_full_iso = None
    if b.last_emptied_sim_s >= 0:
        last_emptied_iso = (sim_epoch + timedelta(seconds=b.last_emptied_sim_s)).isoformat()
    else: last_emptied_iso = None
    return {"bin_id":..., "fill_pct": round(b.fill_pct,1), "status":...,
            "estimated_full_iso":..., "last_emptied_iso":..., ...}
```
**Tahmini dolum vakti:** doluysa/anomaliyse None; değilse ETF saat → sanal saate eklenip ISO tarih.
Frontend popup'ında "Tahmini Dolum: 15 Haz 14:30". **🔗 Çağıran:** `state_snapshot`.

### `_truck_to_dict` — kamyonu frontend JSON'una çevir
```python
def _truck_to_dict(t, depot_lat, depot_lon) -> dict:
    remaining   = [[s.lat, s.lon] for s in t.stops[t.current_stop_idx:]]
    route_ahead = [[t.lat, t.lon]] + remaining + [[depot_lat, depot_lon]]
    return {"truck_id":..., "status":..., "progress":..., "capacity_used":...,
            "full_latlons": t.full_latlons, "route_ahead": route_ahead, ...}
```
`route_ahead` (parlak çizgi, önündeki yol) + `full_latlons` (soluk çizgi, tüm rota) →
frontend iki çizgiyle "nereye gitti / gidecek" gösterir. **🔗 Çağıran:** `state_snapshot`.

---

# ALAN E — Engine Kurulumu

```python
def __init__(self) -> None:
    self.is_running = False
    self.speed_multiplier = 3600
    self._sim_epoch = datetime(2024, 1, 1, tzinfo=timezone.utc)   # sanal başlangıç
    self._sim_s = 0.0                                             # sanal zaman (saniye)
    self.depot_lat/lon = _DEFAULT_DEPOT_LAT/LON
    self.algo_bins/fixed_bins: dict[str, BinState] = {}
    self.algo_trucks/fixed_trucks: list[TruckRoute] = []
    self.algo_kpis/fixed_kpis = self._zero_kpis()
    self.recent_anomalies/fill_history: list = []
    self._event_manager = EventManager()       # environment'tan
    self._predictor     = FillPredictor()      # predictor'dan
    self._last_zone_visit: dict[int,float] = {}
    self._fixed_routes: list[list[Stop]] = []
    self._last_fill_s          = -FILL_JOB_INTERVAL_S       # negatif → ilk tick hemen çalışsın
    self._last_dispatch_algo_s = -DISPATCH_ALGO_INTERVAL_S
    self._last_fixed_day_key   = None
    self._fixed_route_cursor   = 0
    self._next_anomaly_s       = self._rand_anomaly_s()
    self._truck_ctr            = 0
    self._task: asyncio.Task | None = None
```
**İki dünya = ikişer kopya veri yapısı.** Önemli hileler:
- `_sim_s` → sanal zaman; `speed_multiplier` ile hızlanır.
- `_last_fill_s = -FILL_JOB_INTERVAL_S` → **negatif başlatma:** ilk tick'te `0-(-3600)≥3600` → dolum hemen çalışır.

```python
@staticmethod
def _zero_kpis() -> dict:
    return {"distance_km":0.0,"fuel_l":0.0,"co2_kg":0.0,"cost_tl":0.0,
            "dispatch_count":0,"overflow_events":0,"overflow_count":0,
            "bins_collected":0,"load_collected":0.0}

@property
def virtual_clock(self) -> datetime:
    return self._sim_epoch + timedelta(seconds=self._sim_s)
```
- `_zero_kpis` → sıfır KPI sözlüğü. **🔗 Çağıran:** `__init__`, `reset`.
- `virtual_clock` → `_sim_s` → gerçek tarih/saat. **🔗 Çağıran:** `_job_fill` (`.hour`), `_job_dispatch_fixed` (`.day`), snapshot'lar.

---

# ALAN F — Veri Yükleme

### `load_bins` — DB'den iki dünyaya yükle
```python
def load_bins(self, bin_rows) -> None:
    self.algo_bins.clear(); self.fixed_bins.clear()
    for row in bin_rows:
        bid = row["bin_id"]
        label = row.get("fill_label") or "C"
        lo, hi = FILL_RATE_RANGES.get(label, (0.8, 2.0))
        fill_rate = round(random.uniform(lo, hi), 3)
        region = row.get("region") or "Unknown"
        common = dict(bin_id=bid, lat=float(row["lat"]), lon=float(row["lon"]),
                      region=region, fill_label=label,
                      distance_label=int(row.get("distance_label") or 2),
                      district_type=assign_district(region),    # environment
                      fill_rate=fill_rate)
        self.algo_bins[bid]  = BinState(**common)
        self.fixed_bins[bid] = BinState(**common)               # aynı parametre, ayrı nesne
    self._compute_depot()
    self._precompute_fixed_routes()
    self._predictor.assign_zones(list(self.algo_bins.values()))  # predictor K-means
```
**🔗 Çağıran:** `main.py → lifespan` (uygulama açılışında DB'den kovaları çeker).
**🔗 Çağırdıkları:** `assign_district` (environment), `_compute_depot`, `_precompute_fixed_routes`,
`predictor.assign_zones`. İki dünya **aynı fill_rate** paylaşır (fiziksel olarak aynı kova).

### `_compute_depot`
```python
def _compute_depot(self) -> None:
    if not self.algo_bins: return
    northernmost = max(self.algo_bins.values(), key=lambda b: b.lat)
    self.depot_lat = round(northernmost.lat + DEPOT_NORTH_OFFSET, 6)
    self.depot_lon = round(northernmost.lon, 6)
```
Depo = en kuzey kovanın biraz kuzeyi. Tüm rotaların başlangıç/bitiş noktası.

### `_precompute_fixed_routes` — Sweep heuristiği
```python
def _precompute_fixed_routes(self) -> None:
    def _angle_from_depot(b):
        return math.atan2(b.lon - self.depot_lon, b.lat - self.depot_lat)
    all_bins = sorted(self.fixed_bins.values(), key=_angle_from_depot)   # açıya göre sırala
    self._fixed_routes.clear()
    for i in range(0, len(all_bins), FIXED_ROUTE_SIZE):                  # 20'lik dilimler
        chunk    = all_bins[i:i + FIXED_ROUTE_SIZE]
        nn_order = _nearest_neighbor(chunk, self.depot_lat, self.depot_lon)
        stops    = [Stop(b.bin_id, b.lat, b.lon) for b in nn_order]
        self._fixed_routes.append(_two_opt_route(stops, self.depot_lat, self.depot_lon))
```
**Sweep (Gillett & Miller 1974).** Kovalar depo açısına göre sıralanıp 20'lik radyal dilimlere
bölünür → her dilim NN+2-opt rota. Gerçek belediye "yönlü rota" pratiği; uzağa gidip döner →
fixed daha uzun km (DPET'e karşı kasıtlı dezavantaj). **Startup'ta bir kez** çalışır.

---

# ALAN G — Kontrol (start/stop/reset)

```python
async def start(self) -> None:
    if self.is_running: return
    self.is_running = True
    self._task = asyncio.create_task(self._loop())     # arka plan görevi

async def stop(self) -> None:
    self.is_running = False
    if self._task:
        self._task.cancel()
        try: await self._task
        except asyncio.CancelledError: pass
        self._task = None
```
`start` → `_loop`'u **bloke etmeyen** asyncio görevi olarak başlatır. `stop` → iptal eder, temiz biter.
**🔗 Çağıran:** `routers/simulation.py` (`/start`, `/stop`), `main.py lifespan` (shutdown).

```python
def reset(self) -> None:
    for b in list(self.algo_bins.values()) + list(self.fixed_bins.values()):
        b.fill_pct=0.0; b.status="EMPTY"; b.is_anomaly=False; b.anomaly_end_sim_s=0.0
    self.algo_trucks.clear(); self.fixed_trucks.clear()
    self.algo_kpis = self._zero_kpis(); self.fixed_kpis = self._zero_kpis()
    self.recent_anomalies.clear(); self.fill_history.clear()
    self._event_manager.reset(); self._predictor.reset()   # alt modülleri de sıfırla
    self._last_zone_visit.clear()
    self._sim_s = 0.0; self._last_fill_s = -FILL_JOB_INTERVAL_S; ...
```
Her şeyi başa alır. **`_predictor.reset()`** → öğrenmeyi siler ama **zone'ları korur**.
**🔗 Çağıran:** `routers/simulation.py → /reset`.

---

# ALAN H — Ana Döngü (`_loop`) ⭐

```
   ┌─────────────────────── TICK (her 0.2 gerçek sn) ───────────────────────┐
   │  _sim_s += 0.2 × speed_multiplier   (3600x → +12 sanal dakika)          │
   │      ▼                                                                  │
   │  1. _job_events()       talep olayları (konser/maç)                     │
   │  2. _job_fill()         kovalar dolar       ← her 1 sim-saat            │
   │  3. _job_dispatch_algo()DPET kamyon çıkarır  ← her 1 sim-saat           │
   │  4. _job_dispatch_fixed()sabit rota          ← her gün 06:00            │
   │  5. _job_anomaly()      rastgele anomali     ← her 5-20 sim-dk          │
   │  6. _heal_anomalies()   biten anomaliler                                │
   │  7. _advance_trucks()   kamyonlar hareket eder ← her tick               │
   │      ▼                                                                  │
   │  await asyncio.sleep(0.2)                                               │
   └────────────────────────────────────────────────────────────────────────┘
```

```python
TICK_REAL_S = 0.2

async def _loop(self) -> None:
    while self.is_running:
        self._sim_s += self.TICK_REAL_S * self.speed_multiplier
        self._job_events()
        self._job_fill()
        self._job_dispatch_algo()
        self._job_dispatch_fixed()
        self._job_anomaly()
        self._heal_anomalies()
        self._advance_trucks()
        await asyncio.sleep(self.TICK_REAL_S)
```
**Sıralama önemli:** önce talep (event) → dolum → dispatch → hareket. Her işin **kendi iç
zamanlayıcısı** var (fill her 1 saat, dispatch her 1 saat, ama advance her tick).
`await asyncio.sleep` → CPU'yu bırakır, web isteklerine yer açar.

---

# ALAN I — Fill Job (`_job_fill`) ⭐

```python
def _job_fill(self) -> None:
    if self._sim_s - self._last_fill_s < FILL_JOB_INTERVAL_S:   # her 1 sim-saat
        return
    self._last_fill_s = self._sim_s
    hour   = self.virtual_clock.hour
    events = self._event_manager.active(self._sim_s)            # aktif eventler
    for world, kpis, world_name in ((self.algo_bins, self.algo_kpis, "algo"),
                                    (self.fixed_bins, self.fixed_kpis, "fixed")):
        for b in world.values():
            if b.is_anomaly: continue
            rate = effective_fill_rate(b.fill_rate, b.district_type, hour, events)
            old_pct = b.fill_pct
            b.fill_pct = min(100.0, b.fill_pct + rate)
            if b.fill_pct >= 100.0:
                kpis["overflow_events"] += 1                    # her tick (şiddet)
                if old_pct < 100.0:
                    kpis["overflow_count"] += 1                 # yeni olay (sıklık)
                    self._append_history("OVERFLOW", b, world_name)
                if world_name == "algo" and b.overflow_start_s < 0:
                    b.overflow_start_s = self._sim_s            # aging başlangıcı
            b.refresh_status()
```
- `if ... < FILL_JOB_INTERVAL_S: return` → her 1 sim-saat (iç zamanlayıcı).
- **`for world,... in ((algo),(fixed))` → adil karşılaştırma:** iki dünya **aynı `effective_fill_rate`**.
- **İki taşma sayacı:** `overflow_events` (her tick = bin-saat) vs `overflow_count` (yeni olay).
- **🔗 Çağırdıkları:** `effective_fill_rate` (environment), `_append_history` (→ predictor), `refresh_status`.

---

# ALAN J — Sensör Enjeksiyonu (`inject_sensor_reading`) ⭐

```
ESP32 → POST /state-change → bins_service.log_state_change → engine.inject_sensor_reading
                                                                       │
                              ┌────────────────────────────────────────┘
                              ▼
              SENSOR_ERROR? ──evet──► iki dünyada anomali penceresi + panoya push
                    │ hayır
                    ▼
              median_distance_cm var? ──evet──► ESP32 ile AYNI formül: fill_pct
                    │ hayır                                              │
                    ▼                                                    │
              enum → temsili %  ◄────────────────────────────────────────┘
                    ▼
              iki dünyaya yaz: boşalma? → empty()+EMPTIED ; yeni %100? → overflow
```

```python
def inject_sensor_reading(self, bin_id, enum_state, median_distance_cm=None) -> None:
    if not self.algo_bins and not self.fixed_bins: return
    if enum_state == "SENSOR_ERROR":
        end_s = self._sim_s + SENSOR_ANOMALY_DURATION_S
        for world in (self.algo_bins, self.fixed_bins):
            b = world.get(bin_id)
            if b is None: continue
            b.status="SENSOR_ERROR"; b.is_anomaly=True; b.anomaly_end_sim_s=end_s
        self._push_sensor_anomaly(bin_id, "SENSOR_NOT_FOUND_ERROR")
        return
    if median_distance_cm is not None and median_distance_cm > 0:
        effective = max(0.0, median_distance_cm - SENSOR_OFFSET_CM)
        filled    = max(0.0, min(SENSOR_BIN_HEIGHT_CM, SENSOR_BIN_HEIGHT_CM - effective))
        fill_pct  = (filled / SENSOR_BIN_HEIGHT_CM) * 100.0       # firmware ile AYNI
    else:
        fill_pct  = SENSOR_ENUM_FILL_PCT.get(enum_state, 0.0)
    fill_pct = max(0.0, min(100.0, fill_pct))
    for world, kpis, world_name in ((algo...),(fixed...)):
        b = world.get(bin_id)
        if b is None: continue
        old_pct = b.fill_pct
        b.is_anomaly=False; b.anomaly_end_sim_s=0.0; b.fill_pct=fill_pct
        if old_pct >= FULL_THRESHOLD and fill_pct < FULL_THRESHOLD:
            b.empty(self._sim_s); self._append_history("EMPTIED", b, world_name); continue
        if fill_pct >= 100.0 and old_pct < 100.0:
            kpis["overflow_count"] += 1; kpis["overflow_events"] += 1
            if world_name == "algo" and b.overflow_start_s < 0:
                b.overflow_start_s = self._sim_s
            self._append_history("OVERFLOW", b, world_name)
        b.refresh_status()
```
**🔗 Çağıran:** `bins_service.log_state_change` (gerçek ESP32 verisi). Sentetik dolumu **override eder**.
Fill yüzdesi firmware'le **birebir aynı formül** (`SENSOR_OFFSET_CM`/`SENSOR_BIN_HEIGHT_CM`).

```python
def _push_sensor_anomaly(self, bin_id, event_type) -> None:
    self.recent_anomalies.append({"bin_id":bin_id, "event_type":event_type,
        "virtual_time":self.virtual_clock.isoformat(), "details":f"{event_type} @ {bin_id} (real sensor)"})
    if len(self.recent_anomalies) > 50: self.recent_anomalies.pop(0)
```
Canlı pano akışına anomali ekler (50 sınırı). **🔗 Çağıran:** `inject_sensor_reading`.

---

# ALAN K — Rota Genişletme

### `_corridor_bins` — yol üstü kovalar
```python
def _corridor_bins(self, available, excluded) -> list[BinState]:
    candidates = set()
    for truck in self.algo_trucks:
        if truck.status == "done": continue
        waypoints = [(truck.lat, truck.lon)] + [(s.lat, s.lon) for s in truck.stops[truck.current_stop_idx:]]
        for i in range(len(waypoints) - 1):
            a, b_pt = waypoints[i], waypoints[i+1]
            for bid, b in available.items():
                if bid in excluded or bid in candidates: continue
                if b.is_anomaly or b.fill_pct < CORRIDOR_MIN_FILL: continue
                if _dist_to_segment_km(b.lat, b.lon, *a, *b_pt) <= CORRIDOR_RADIUS_KM:
                    candidates.add(bid)
    return [available[bid] for bid in candidates if bid in available]
```
Kamyon rotalarının bacaklarına **650m yakın, %70+ dolu** kovalar = "yoldan geçerken bedavaya al".
**🔗 Çağıran:** `_job_dispatch_algo`. **Çağırdığı:** `_dist_to_segment_km`.

### `_try_extend_truck` — mevcut kamyona ekle
```python
def _try_extend_truck(self, urgent_bins, max_detour=MAX_DETOUR_RATIO) -> set[str]:
    extended = set()
    for b in urgent_bins:
        new_stop = Stop(b.bin_id, b.lat, b.lon)
        bin_load = (b.fill_pct / 100.0) * BIN_VOLUME_FRACTION
        best_truck=None; best_extra_km=inf; best_insert_pos=-1
        for truck in self.algo_trucks:
            if truck.status == "done": continue
            if TRUCK_CAPACITY - truck.capacity_used < bin_load: continue   # kapasite yok
            rem_km = _remaining_route_km(truck, ...)
            if rem_km < 0.1: continue
            extra_km, pos = _insertion_km(truck, new_stop, ...)
            if extra_km / rem_km <= max_detour and extra_km < best_extra_km:
                best_extra_km, best_truck, best_insert_pos = extra_km, truck, pos
        if best_truck is not None:
            best_truck.stops.insert(best_insert_pos, new_stop)
            best_truck.full_latlons = _build_latlons(best_truck.stops, ...)
            extended.add(b.bin_id)
            extra_fuel = best_extra_km * FUEL_PER_KM * (1 + WEIGHT_MULTIPLIER * 0.75)
            self.algo_kpis["distance_km"] += best_extra_km
            self.algo_kpis["fuel_l"]      += extra_fuel
            self.algo_kpis["co2_kg"]      += best_extra_km * CO2_PER_KM
            self.algo_kpis["cost_tl"]     += extra_fuel * FUEL_PRICE_TL
    return extended
```
Acil kovaları **yeni sefer açmadan** mevcut kamyonlara sokar (kapasite + sapma ≤ %30 koşuluyla).
**KPI'ya sadece ek mesafe eklenir, `DISPATCH_COST_TL` yok** → bu yüzden ucuz, DPET'in kozu.
**🔗 Çağıran:** `_job_dispatch_algo`. **Çağırdıkları:** `_remaining_route_km`, `_insertion_km`, `_build_latlons`.

---

# ALAN L — Dispatch Algo (`_job_dispatch_algo`) — 4 Katman ⭐⭐

```
                    _job_dispatch_algo (her 1 sim-saat)
                              │
     ┌────────────────────────┼────────────────────────┐
     ▼ ÖN: mevcut kamyonları kullan                     │
   _try_extend_truck(acil %90+)  →  _corridor_bins      │
     │                                                  │
     ▼ TIER 0 — Aging: %100'de 4+ saat bekleyen → ekstra kamyon
     ▼ TIER 1 — Acil zone: predictor.urgent_zone_bins (ETF≤2sa) → dpet_dispatch
     ▼ TIER 2 — Coverage: her zone adaptif aralıkla → coverage_zone_bins → dpet_dispatch
     ▼ FALLBACK — hiç dispatch yoksa ve %90+ kova varsa
                              │
                              ▼
                  her route → _create_truck("algo")
```

### Hazırlık + ekleme/koridor
```python
if self._sim_s - self._last_dispatch_algo_s < DISPATCH_ALGO_INTERVAL_S: return
self._last_dispatch_algo_s = self._sim_s
claimed   = self._active_stop_bin_ids(self.algo_trucks)              # rotadakiler
available = {b.bin_id: b for b in self.algo_bins.values() if b.bin_id not in claimed}
urgent       = [b for b in available.values() if b.fill_pct >= EXTENSION_FILL_THRESHOLD and not b.is_anomaly]
extended_ids = self._try_extend_truck(urgent) if urgent and self.algo_trucks else set()
if self.algo_trucks:
    corridor = self._corridor_bins(available, claimed | extended_ids)
    if corridor: extended_ids |= self._try_extend_truck(corridor, MAX_CORRIDOR_DETOUR_RATIO)
available = {bid: b for bid, b in available.items() if bid not in extended_ids}
dispatched_ids = set()
```

### İç fonksiyon — `_dispatch_zone_bins`
```python
def _dispatch_zone_bins(zone_id, zone_bins) -> None:
    if len(self.algo_trucks) >= MAX_FLEET_SIZE: return
    anchor_ids = {b.bin_id for b in zone_bins}
    opportunistic = [b for bid, b in available.items()
                     if bid not in anchor_ids and bid not in dispatched_ids
                     and not b.is_anomaly and b.fill_pct >= OPPORTUNISTIC_FILL_THRESHOLD
                     and self._predictor.zone_of(bid) == zone_id]
    combined = [b for b in zone_bins if b.bin_id not in dispatched_ids] + opportunistic
    if not combined: return
    routes = dpet_dispatch(bins=combined, active_truck_count=len(self.algo_trucks),
                           hour=self.virtual_clock.hour, depot_lat=..., depot_lon=...,
                           max_fleet=MAX_FLEET_SIZE, max_stops=ALGO_MAX_STOPS)
    for route in routes:
        self._create_truck("algo", route, self.algo_trucks, self.algo_kpis)
        dispatched_ids.update(s.bin_id for s in route)
    self._last_zone_visit[zone_id] = self._sim_s
```
Zone'a giderken **%55+ diğer kovaları da** ekler (fırsatçı), sonra **`dpet_dispatch`** (asıl algoritma) çağrılır.

### Tier 0 — Priority Aging
```python
aged_bins = [b for b in available.values()
             if b.overflow_start_s >= 0
             and self._sim_s - b.overflow_start_s >= AGING_THRESHOLD_S and not b.is_anomaly]
if len(aged_bins) >= AGING_MIN_BINS and len(self.algo_trucks) < MAX_FLEET_SIZE:
    routes = dpet_dispatch(bins=aged_bins, ...)
    for route in routes: self._create_truck(...); dispatched_ids.update(...)
```
%100'de **4+ saat** bekleyenler → ekstra kamyon. "Hiçbir kova çok uzun taşmış kalmasın".

### Tier 1 — Acil Zone
```python
urgent_zones = self._predictor.urgent_zone_bins(available, URGENT_ZONE_ETF_H, URGENT_ZONE_MIN_BINS)
for zone_id, zone_bins in urgent_zones.items():
    _dispatch_zone_bins(zone_id, zone_bins)
```
Predictor'dan **ETF ≤ 2 saat** kova yoğun zone'lar → erken yakalama (taşmadan önce).

### Tier 2 — Coverage Rotation
```python
for zone_id in range(self._predictor.n_zones()):
    if len(self.algo_trucks) >= MAX_FLEET_SIZE: break
    if zone_id in urgent_zones: continue
    last_visit = self._last_zone_visit.get(zone_id, -COVERAGE_INTERVAL_S)
    adaptive_interval = self._predictor.adaptive_coverage_interval_s(zone_id, available, COVERAGE_INTERVAL_S)
    if self._sim_s - last_visit < adaptive_interval: continue
    zone_bins = self._predictor.coverage_zone_bins(available, zone_id, COVERAGE_MIN_FILL)
    if zone_bins: _dispatch_zone_bins(zone_id, zone_bins)
    else: self._last_zone_visit[zone_id] = self._sim_s
```
Her zone **adaptif aralıkla** ziyaret (hızlı zone sık, yavaş seyrek). Acil zone'lar atlanır.

### Fallback
```python
if not dispatched_ids:
    emergency = [b for b in available.values() if b.fill_pct >= FALLBACK_EMERGENCY_FILL and not b.is_anomaly]
    if emergency:
        routes = dpet_dispatch(bins=emergency, ...)
        for route in routes: self._create_truck("algo", route, ...)
```
Güvenlik ağı: hiç dispatch yoksa ama %90+ kova varsa topla.

**🔗 Bu method'un bağlantıları:** `predictor.urgent_zone_bins / coverage_zone_bins /
adaptive_coverage_interval_s / zone_of / n_zones`, `dpet.dpet_dispatch`, `_try_extend_truck`,
`_corridor_bins`, `_create_truck`.

---

# ALAN M — Dispatch Fixed

```python
def _job_dispatch_fixed(self) -> None:
    vc = self.virtual_clock
    if vc.hour < FIXED_DISPATCH_HOUR: return          # 06:00'dan önce çıkma
    day_key = (vc.year, vc.month, vc.day)
    if self._last_fixed_day_key == day_key: return    # günde bir kez
    self._last_fixed_day_key = day_key
    self._fixed_route_cursor = 0
    for _ in range(min(MAX_FLEET_SIZE, len(self._fixed_routes))):
        self._dispatch_next_fixed_route()

def _dispatch_next_fixed_route(self) -> None:
    if self._fixed_route_cursor >= len(self._fixed_routes): return
    if len(self.fixed_trucks) >= MAX_FLEET_SIZE: return
    route = self._fixed_routes[self._fixed_route_cursor]
    self._fixed_route_cursor += 1
    if route: self._create_truck("fixed", route, self.fixed_trucks, self.fixed_kpis)
```
**Kasıtlı basit (belediye taklidi):** her gün 06:00, günde bir kez, **doluluğa bakmadan**
önceden hesaplı rotaları yola çıkar → yarı boş kovaları da toplar (boşa sefer = DPET'in kazanç kaynağı).
**🔗 Çağıran:** `_loop`, ayrıca `_advance_trucks` (biten kamyon yerine `_dispatch_next_fixed_route`).

---

# ALAN N — Kamyon Oluşturma (`_create_truck`)

```python
def _create_truck(self, route_type, stops, truck_list, kpis) -> None:
    if not stops: return
    self._truck_ctr += 1
    first = stops[0]
    dist_first = _haversine_km(self.depot_lat, self.depot_lon, first.lat, first.lon)
    travel_first = (dist_first / TRUCK_SPEED_KMH) * 3600
    truck = TruckRoute(truck_id=self._truck_ctr, route_type=route_type, stops=stops,
        full_latlons=_build_latlons(stops, ...), lat=depot, lon=depot,
        from_lat=depot, from_lon=depot, to_lat=first.lat, to_lon=first.lon,
        leg_start_sim_s=self._sim_s, leg_end_sim_s=self._sim_s + travel_first,
        to_bin=first.bin_id, status="en_route")
    truck_list.append(truck)
    total_km, total_fuel = _weighted_fuel(stops, self.depot_lat, self.depot_lon)
    co2  = total_km * CO2_PER_KM
    cost = DISPATCH_COST_TL + total_fuel * FUEL_PRICE_TL
    kpis["distance_km"] += total_km; kpis["fuel_l"] += total_fuel
    kpis["co2_kg"] += co2; kpis["cost_tl"] += cost; kpis["dispatch_count"] += 1
```
Rotadan kamyon nesnesi + **KPI güncelleme** (`_weighted_fuel` ile ağırlık-duyarlı; `cost = 2000 + yakıt*45`).
**🔗 Çağıran:** her iki dispatch + `_dispatch_zone_bins`. **Çağırdıkları:** `_haversine_km`, `_build_latlons`, `_weighted_fuel`.

---

# ALAN O — Kamyon İlerlemesi ⭐

### Durum makinesi diyagramı
```
   _create_truck                                          listeden çıkar
        │                                                       ▲
        ▼                                                       │
   ┌─────────┐  varış   ┌───────────┐  durak++  ┌─────────┐  varış  ┌──────┐
   │ en_route│ ───────► │ servicing │ ────────► │returning│ ──────► │ done │
   └─────────┘          └───────────┘           └─────────┘         └──────┘
        ▲                     │ kovayı boşalt
        └──── sonraki durak ──┘ (bins_collected++, b.empty())
```

### `_advance_trucks`
```python
def _advance_trucks(self) -> None:
    s = self._sim_s
    for truck_list, world_bins, world_name, is_fixed in ((algo...,False),(fixed...,True)):
        for truck in truck_list:
            if truck.status != "done": self._step_truck(truck, s, world_bins, world_name)
        done_count = sum(1 for t in truck_list if t.status == "done")
        truck_list[:] = [t for t in truck_list if t.status != "done"]   # done'ları çıkar
        if is_fixed and done_count > 0:
            for _ in range(done_count): self._dispatch_next_fixed_route()  # yerine yenisi
```
`truck_list[:] = [...]` → liste **yerinde** filtrelenir. Sabit dünyada biten kamyon başına yeni rota devreye girer.

### `_step_truck` — durum geçişleri (satır satır)
```python
def _step_truck(self, t, s, world_bins, world_name) -> None:
    if t.status == "en_route":
        if s >= t.leg_end_sim_s:                              # === durağa vardı ===
            t.lat, t.lon = t.to_lat, t.to_lon
            stop = t.stops[t.current_stop_idx]
            t.at_bin = stop.bin_id; t.to_bin = None
            t.status = "servicing"
            t.service_end_sim_s = t.leg_end_sim_s + SERVICE_SIM_MIN * 60
            t.progress = 1.0
            if stop.bin_id in world_bins:                     # kovayı boşalt
                b = world_bins[stop.bin_id]
                bin_load = (b.fill_pct / 100.0) * BIN_VOLUME_FRACTION
                t.capacity_used = min(TRUCK_CAPACITY, t.capacity_used + bin_load)
                self._append_history("EMPTIED", b, world_name)
                kpis = self.algo_kpis if world_name=="algo" else self.fixed_kpis
                kpis["bins_collected"] += 1
                kpis["load_collected"] += b.fill_pct          # toplanan gerçek yük
                b.empty(self._sim_s)
        else:                                                 # === yolda — ara konum ===
            seg = max(1.0, t.leg_end_sim_s - t.leg_start_sim_s)
            t.progress = max(0.0, min(1.0, (s - t.leg_start_sim_s) / seg))
            t.lat = t.from_lat + (t.to_lat - t.from_lat) * t.progress   # LİNEER İNTERPOLASYON
            t.lon = t.from_lon + (t.to_lon - t.from_lon) * t.progress
            t.to_bin = t.stops[t.current_stop_idx].bin_id
    elif t.status == "servicing":
        if s >= t.service_end_sim_s:
            t.current_stop_idx += 1; t.at_bin = None
            if t.current_stop_idx < len(t.stops):             # sonraki durağa bacak kur
                nxt = t.stops[t.current_stop_idx]
                dist = _haversine_km(t.lat, t.lon, nxt.lat, nxt.lon)
                t.from_lat,t.from_lon = t.lat,t.lon; t.to_lat,t.to_lon = nxt.lat,nxt.lon
                t.leg_start_sim_s = s; t.leg_end_sim_s = s + (dist/TRUCK_SPEED_KMH)*3600
                t.to_bin = nxt.bin_id; t.status = "en_route"; t.progress = 0.0
            else:                                             # duraklar bitti → depoya dön
                dist = _haversine_km(t.lat, t.lon, self.depot_lat, self.depot_lon)
                t.from_*=t.*; t.to_*=depot; t.leg_*; t.to_bin=None; t.status="returning"; t.progress=0.0
    elif t.status == "returning":
        if s >= t.leg_end_sim_s:
            t.lat,t.lon = self.depot_lat,self.depot_lon; t.status = "done"
        else:
            seg=max(1.0,...); t.progress=...; t.lat/lon = interpolasyon
```
- **en_route varış:** durağa varır → `servicing`, **kovayı boşaltır** (`bins_collected++`,
  `load_collected += fill_pct`, `_append_history("EMPTIED")`, `b.empty()`).
- **en_route yolda:** `progress` (0-1) ile **lineer interpolasyon** → frontend akıcı hareket çizer.
- **servicing:** 5 dk sonra sonraki durağa bacak ya da `returning`.
- **returning:** depoya varınca `done`.
- **🔗 Çağırdıkları:** `_append_history` (→ predictor), `_haversine_km`, `b.empty()`.

```python
@staticmethod
def _active_stop_bin_ids(truck_list) -> set[str]:
    return {stop.bin_id for truck in truck_list for stop in truck.stops[truck.current_stop_idx:]}
```
Aktif kamyonların **henüz servis etmediği** durakların id kümesi. **🔗 Çağıran:** `_job_dispatch_algo` (`claimed`).

---

# ALAN P — Event / History / Anomaly

### `_job_events`
```python
def _job_events(self) -> None:
    new_event = self._event_manager.tick(self._sim_s)        # environment
    if new_event:
        self.recent_anomalies.append({"bin_id":"CITY",
            "event_type":f"EVENT_{new_event.event_type.upper()}", ...})
        if len(self.recent_anomalies) > 50: self.recent_anomalies.pop(0)
```
EventManager'ı tick'ler; yeni konser/maç varsa panoya yazar. **🔗 Çağırdığı:** `EventManager.tick`.

### `_append_history` — geçmiş + predictor besleme
```python
def _append_history(self, event, b, world) -> None:
    self.fill_history.append({"sim_time":..., "world":world, "bin_id":b.bin_id, "event":event,
                              "fill_pct":round(b.fill_pct,1), "fill_label":..., "fill_rate":...})
    if len(self.fill_history) > MAX_FILL_HISTORY:
        self.fill_history = self.fill_history[-MAX_FILL_HISTORY:]
    if world == "algo":
        self._predictor.record_event(event, b.bin_id, self._sim_s)   # SADECE algo öğrenir
```
Her OVERFLOW/EMPTIED'i geçmişe ekler (CSV export bunu kullanır). **`if world == "algo"`** →
predictor **yalnızca algo dünyasından** öğrenir. **🔗 Çağıran:** `_job_fill`, `inject_sensor_reading`,
`_step_truck`. **Çağırdığı:** `predictor.record_event`.

### `_job_anomaly` — rastgele anomali
```python
ANOMALY_TYPES = ["OVERFLOW_RISK","FILL_ANOMALY","SENSOR_FIXED_VALUE_ERROR","BIN_OFFLINE"]

def _job_anomaly(self) -> None:
    if self._sim_s < self._next_anomaly_s: return
    self._next_anomaly_s = self._sim_s + self._rand_anomaly_s()
    bin_id = random.choice(list(self.algo_bins.keys()))
    atype  = random.choice(self.ANOMALY_TYPES)
    algo_bin, fixed_bin = self.algo_bins.get(bin_id), self.fixed_bins.get(bin_id)
    if atype == "OVERFLOW_RISK":
        target = random.choice(["algo","fixed"])             # SADECE bir dünya (bağımsız)
        b = algo_bin if target=="algo" else fixed_bin; kpis = ...
        if b: b.fill_pct=95.0; b.status="CRITICAL_FULL"; kpis["overflow_events"]+=1
    elif atype == "FILL_ANOMALY":
        for b in (algo_bin, fixed_bin):
            if b: b.fill_pct=0.0; b.refresh_status()
    elif atype in ("SENSOR_FIXED_VALUE_ERROR","BIN_OFFLINE"):
        end_s = self._sim_s + random.uniform(*self.OFFLINE_DURATION_S)
        new_status = "SENSOR_ERROR" if atype=="SENSOR_FIXED_VALUE_ERROR" else "OFFLINE"
        for b in (algo_bin, fixed_bin):
            if b: b.status=new_status; b.is_anomaly=True; b.anomaly_end_sim_s=end_s
    self.recent_anomalies.append({...}); (50 sınırı)
    self._log_anomaly_db(bin_id, atype, {...})
```
Gerçekçilik için rastgele anomali (5-20 sim-dk). `OVERFLOW_RISK` **bir dünyaya** (bağımsız olay),
diğerleri **iki dünyaya** (fiziksel cihaz). **🔗 Çağırdığı:** `_log_anomaly_db`.

```python
def _heal_anomalies(self) -> None:
    for world in (self.algo_bins, self.fixed_bins):
        for b in world.values():
            if b.is_anomaly and 0 < b.anomaly_end_sim_s <= self._sim_s:
                b.is_anomaly = False; b.refresh_status()
```
Süresi dolan anomalileri otomatik iyileştirir.

```python
@staticmethod
def _log_anomaly_db(bin_id, event_type, details) -> None:
    try:
        from .database import SessionLocal              # LAZY import (döngü kırma)
        from .services.anomaly_service import log_anomaly_event
        db = SessionLocal()
        try: log_anomaly_event(db, bin_id, AnomalyType(event_type), details); db.commit()
        finally: db.close()
    except Exception: pass                              # DB hatası simülasyonu bozmasın
```
**🔗 Bağlantı:** `services/anomaly_service.log_anomaly_event` (DB'ye yazar). Lazy import +
`try/except pass` ile sağlamlık.

---

# ALAN Q — Snapshot'lar (API çıktısı)

### `state_snapshot` → `GET /api/simulation/live-state`
```python
def state_snapshot(self) -> dict:
    return {"virtual_clock":..., "is_running":..., "speed_multiplier":..., "depot_lat/lon":...,
        "algo_bins": [_bin_to_dict(b, self._sim_s, self._sim_epoch) for b in self.algo_bins.values()],
        "fixed_bins":[...], "algo_trucks":[_truck_to_dict(t,...) for t in self.algo_trucks],
        "fixed_trucks":[...], "active_events":[{...} for e in self._event_manager.active(self._sim_s)]}
```
Tüm kova + kamyonların anlık fotoğrafı. **🔗 Çağıran:** `routers/simulation.py → /live-state`
(frontend her 1 sn). **Çağırdıkları:** `_bin_to_dict`, `_truck_to_dict`.

### `kpis_snapshot` → `GET /api/simulation/live-kpis`
```python
def kpis_snapshot(self) -> dict:
    def _rnd(d): return {k:(round(v,1) if isinstance(v,float) else v) for k,v in d.items()}
    a = _rnd(self.algo_kpis); f = _rnd(self.fixed_kpis)
    return {"algo":a, "fixed":f,
            "savings": {"co2_kg": round(f["co2_kg"]-a["co2_kg"],1),
                        "fuel_l": round(f["fuel_l"]-a["fuel_l"],1),
                        "cost_tl": round(f["cost_tl"]-a["cost_tl"],1),
                        "overflow_diff": f["overflow_count"]-a["overflow_count"]}}
```
**`savings = fixed − algo`** → pozitif = DPET kazandı. Frontend "ALGORİTMA TASARRUFU" şeridi.
**🔗 Çağıran:** `routers/simulation.py → /live-kpis` (frontend her 2 sn).

```python
engine = SimulationEngine()   # modül sonu — tek global singleton
```
**🔗 Bağlantı:** Tüm uygulama `from .simulation_engine import engine` ile bu örneği paylaşır
(main, router, bins_service).

---

## Method Çağrı Haritası (özet)

```
DIŞARIDAN GİRİŞLER:
  main.lifespan ─────────► load_bins
  router /start /stop ───► start / stop
  router /reset ─────────► reset
  router /live-state ────► state_snapshot
  router /live-kpis ─────► kpis_snapshot
  bins_service ──────────► inject_sensor_reading   (gerçek sensör)

İÇ DÖNGÜ (_loop her 0.2 sn):
  _job_events ──► EventManager.tick
  _job_fill ────► effective_fill_rate ─┐
                  _append_history ──────┼─► predictor.record_event
  _job_dispatch_algo ─► predictor.{urgent_zone_bins, coverage_zone_bins,
                                    adaptive_coverage_interval_s, zone_of, n_zones}
                     ─► dpet.dpet_dispatch
                     ─► _try_extend_truck / _corridor_bins
                     ─► _create_truck ─► _weighted_fuel
  _job_dispatch_fixed ─► _dispatch_next_fixed_route ─► _create_truck
  _job_anomaly ─► _log_anomaly_db ─► anomaly_service.log_anomaly_event (DB)
  _advance_trucks ─► _step_truck ─► _append_history, b.empty()
```

---

## 🎤 Viva için Altın Noktalar

1. **İki dünya, tek `_job_fill`** → adil karşılaştırmanın garantisi (aynı talep verisi).
2. **`_job_dispatch_algo`'nun 4 katmanı** (Aging → Acil zone → Coverage → Fallback) + ön ekleme/koridor.
3. **`_step_truck` durum makinesi** + `progress` lineer interpolasyonu (UI akıcılığı).
4. **`kpis_snapshot`'taki `savings = fixed − algo`** → projenin ölçülebilir sonucu.
5. **Gerçek sensör entegrasyonu** (`inject_sensor_reading`) firmware ile birebir formül paylaşır.

← İlk bölüme dön: [Bölüm 1 — API ve Veritabanı](KOD_DETAY_1_API_VE_VERITABANI.md)
