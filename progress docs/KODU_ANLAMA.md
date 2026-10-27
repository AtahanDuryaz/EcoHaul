# EcoHaul — Kodu Anlama Rehberi (Modül Modül, Satır Satır)

Bu doküman, EcoHaul projesinin **her önemli kod parçasını** modül modül ve satır
numaralı snippet'lerle açıklar. Her bölümün sonunda **"Nasıl aratmalıyım?"** kutusu
vardır — kendi editörünüzde (VS Code arama, `grep`, `ripgrep`) ilgili kodu hızlıca
bulmanızı sağlar.

> **Snippet okuma kuralı:** Her snippet'in solundaki sayı, o satırın dosyadaki
> gerçek satır numarasıdır. `dosya.py:42` gösterimi → "dosya.py'nin 42. satırı".

---

## İçindekiler

1. [Mimari Genel Bakış](#1-mimari-genel-bakış)
2. [Veritabanı Şeması — `init.sql`](#2-veritabanı-şeması--initsql)
3. [DB Bağlantısı — `database.py`](#3-db-bağlantısı--databasepy)
4. [Veri Şemaları — `schemas.py`](#4-veri-şemaları--schemaspy)
5. [API Giriş Noktası — `main.py`](#5-api-giriş-noktası--mainpy)
6. [Bin Servisi — `bins_service.py`](#6-bin-servisi--bins_servicepy)
7. [Anomali Servisi — `anomaly_service.py`](#7-anomali-servisi--anomaly_servicepy)
8. [DPET Algoritması — `dpet.py`](#8-dpet-algoritması--dpetpy)
9. [Çevre/Talep Modeli — `environment.py`](#9-çevretalep-modeli--environmentpy)
10. [Tahmin + Zone — `predictor.py`](#10-tahmin--zone--predictorpy)
11. [Simülasyon Motoru — `simulation_engine.py`](#11-simülasyon-motoru--simulation_enginepy)
12. [Simülasyon Router — `routers/simulation.py`](#12-simülasyon-router--routerssimulationpy)
13. [ESP32 Firmware — `ESP32-Sensor.ino`](#13-esp32-firmware--esp32-sensorino)
14. [Frontend API Katmanı — `api.js`](#14-frontend-api-katmanı--apijs)
15. [Frontend Ana Harita — `App.jsx` + `MapView.jsx`](#15-frontend-ana-harita--appjsx--mapviewjsx)
16. [Frontend Simülasyon Paneli — `SimulationPage.jsx`](#16-frontend-simülasyon-paneli--simulationpagejsx)
17. [Uçtan Uca Akışlar (Sık Sorulanlar)](#17-uçtan-uca-akışlar)

---

## 1. Mimari Genel Bakış

```
┌─────────────┐    HTTP POST       ┌──────────────────────────────────┐
│  ESP32 +    │  state-change /    │            FastAPI Backend         │
│  HC-SR04    │──  heartbeat   ──▶ │  main.py (router'lar + lifespan)   │
└─────────────┘                    │   ├─ services/ (DB CRUD + anomali) │
                                   │   ├─ simulation_engine.py (canlı)  │
┌─────────────┐    HTTP GET        │   │    ├─ dpet.py (algoritma)      │
│  React SPA  │◀── /api/...    ──  │   │    ├─ environment.py (talep)   │
│  (Vite)     │   poll 1–3 sn      │   │    └─ predictor.py (zone/ETF)  │
└─────────────┘                    │   └─ database.py → PostgreSQL+PostGIS│
                                   └──────────────────────────────────┘
```

**İki paralel dünya fikri** projenin kalbidir: aynı bin'ler üzerinde
- **`algo`** dünyası → DPET dinamik dispatch
- **`fixed`** dünyası → her sabah 06:00 hesaplanan sabit rotalar

Aynı dolum verisiyle çalışıp KPI'ları (km, yakıt, CO₂, taşma) karşılaştırılır.

> ### 🔍 Nasıl aratmalıyım?
> - **"İki dünya nerede tanımlı?"** → `grep -n "algo_bins\|fixed_bins" backend/app/simulation_engine.py`
> - **"Hangi endpoint'ler var?"** → `grep -rn "@app.get\|@app.post\|@router" backend/app`

---

## 2. Veritabanı Şeması — `init.sql`

[backend/database/init.sql](../backend/database/init.sql) üç tablo + PostGIS uzantısı tanımlar.

**`bins` tablosu** — fiziksel kovalar + IoT durum özetleri:

```sql
 3  CREATE TABLE IF NOT EXISTS bins (
 4      id SERIAL PRIMARY KEY,
 5      bin_id TEXT UNIQUE NOT NULL,
 6      latitude DOUBLE PRECISION NOT NULL,
 7      longitude DOUBLE PRECISION NOT NULL,
 8      status TEXT NOT NULL DEFAULT 'OFFLINE',
 9      region TEXT NOT NULL,
10      last_emptied_at TIMESTAMP NULL,
12      fill_level TEXT NULL,              -- son enum (EMPTY/FULL/...)
13      is_active BOOLEAN NOT NULL DEFAULT TRUE,
14      last_seen_at TIMESTAMP NULL,       -- son heartbeat/state-change
16      last_enum_transition TEXT NULL,    -- "EMPTY->FULL" özeti
21      geom GEOGRAPHY(Point, 4326) NOT NULL  -- coğrafi sorgular için
22  );
```

- `geom GEOGRAPHY(Point, 4326)` (satır 21) → PostGIS coğrafi tipi; `idx_bins_geom`
  GIST index'i (satır 34) ile "şu noktaya en yakın bin" gibi sorgular hızlanır.

**`telemetry`** (satır 24-30) → her ölçüm bir satır (`enum_state` + ham `raw_distance_cm`).
**`event_log`** (satır 41-47) → anomali kayıtları.

```sql
35  CREATE INDEX IF NOT EXISTS idx_telemetry_bin_id_created_at ON telemetry(bin_id, created_at DESC);
```
Bu index (satır 35) "bir bin'in son N ölçümü" sorgusunu hızlandırır — anomali tespitinde kritik.

> ### 🔍 Nasıl aratmalıyım?
> - **"Hangi tablolar var?"** → `grep -n "CREATE TABLE" backend/database/init.sql`
> - **"Bir kolon nerede kullanılıyor?"** (ör. `last_enum_transition`) → `grep -rn "last_enum_transition" backend`

---

## 3. DB Bağlantısı — `database.py`

[backend/app/database.py](../backend/app/database.py) tüm SQLAlchemy bağlantısını kurar.

```python
10  DATABASE_URL = os.getenv(
11      "DATABASE_URL",
12      "postgresql+psycopg://postgres:postgres@localhost:5432/ecohaul",
13  )
15  engine = create_engine(DATABASE_URL, pool_pre_ping=True)
16  SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
```

- **Satır 10-13:** Bağlantı dizesi `.env`'den okunur; yoksa localhost varsayılanı.
- **Satır 15:** `pool_pre_ping=True` → kopuk bağlantıları otomatik tespit edip yeniler.
- **Satır 16:** `SessionLocal` bir session **fabrikası**; her istekte yeni session açılır.

```python
19  def get_db() -> Generator[Session, None, None]:
20      db = SessionLocal()
21      try:
22          yield db
23      finally:
24          db.close()
```

- **Satır 19-24:** FastAPI **dependency** kalıbı. `yield` ile session verilir, istek
  bitince `finally` bloğu garantili olarak kapatır. `main.py`'de `Depends(get_db)` ile kullanılır.

> ### 🔍 Nasıl aratmalıyım?
> - **"DB session nasıl alınıyor?"** → `grep -rn "Depends(get_db)" backend/app`
> - **"Bağlantı dizesi nereden geliyor?"** → `grep -rn "DATABASE_URL" backend`

---

## 4. Veri Şemaları — `schemas.py`

[backend/app/schemas.py](../backend/app/schemas.py) Pydantic modelleri = API'nin giriş/çıkış sözleşmesi.

```python
 7  class FillLevelEnum(str, Enum):
 8      EMPTY = "EMPTY"
 9      FULL = "FULL"
10      CRITICAL_FULL = "CRITICAL_FULL"
11      SENSOR_ERROR = "SENSOR_ERROR"
```
- **Satır 7-11:** Doluluk seviyesi enum'u. `str, Enum`'dan türediği için hem string
  gibi davranır (JSON'a `"FULL"` yazılır) hem tip güvenliği sağlar. **ESP32 firmware'inin
  gönderdiği değerlerle birebir aynı** olmalı (bkz. Bölüm 13).

```python
45  class StateChangeIn(BaseModel):
46      enum_state: FillLevelEnum
47      median_distance_cm: float | None = None
48      event_timestamp: datetime | None = None
```
- **Satır 45-48:** ESP32'nin `POST /state-change` ile gönderdiği gövde. `median_distance_cm`
  opsiyonel → sensör hatası durumunda gelmeyebilir.

```python
23  class BinOut(BaseModel):       # GET /api/bins yanıtı
55  class AnomalyEventOut(BaseModel):  # GET /api/anomalies yanıtı
```
- `BinOut` (satır 23) çıkış modeli; alanların çoğu `| None` çünkü bir bin henüz
  IoT verisi göndermemiş olabilir.

> ### 🔍 Nasıl aratmalıyım?
> - **"Bir endpoint hangi alanları kabul ediyor?"** → `grep -n "class.*In" backend/app/schemas.py`
> - **"FillLevel enum nerede kontrol ediliyor?"** → `grep -rn "FillLevelEnum\." backend/app`

---

## 5. API Giriş Noktası — `main.py`

[backend/app/main.py](../backend/app/main.py) FastAPI uygulamasını kurar.

**Lifespan — uygulama açılış/kapanış kancası:**

```python
16  @asynccontextmanager
17  async def lifespan(_app: FastAPI):
19      db = SessionLocal()
20      try:
21          rows = db.execute(text("""
22              SELECT bin_id, latitude AS lat, longitude AS lon,
23                     region, fill_label, distance_label
24              FROM bins ORDER BY bin_id
26          """)).mappings().all()
27          engine.load_bins([dict(r) for r in rows])
...
32      yield
34      await engine.stop()
```

- **Satır 16-27:** Uygulama **başlarken** DB'den tüm bin'leri çekip simülasyon motoruna
  yükler (`engine.load_bins`). `yield`'den (satır 32) önceki kod = startup, sonrası = shutdown.
- **Satır 34:** Kapanışta simülasyon döngüsü temiz şekilde durdurulur.

**CORS + endpoint'ler:**

```python
40  app.add_middleware(
41      CORSMiddleware,
42      allow_origins=["*"],     # tüm origin'lere izin (geliştirme kolaylığı)
...
54  @app.get("/api/bins", response_model=list[BinOut])
55  def get_bins(db: Session = Depends(get_db)) -> list[dict]:
56      return fetch_bins(db)
```

- **Satır 54-56:** Endpoint'ler **çok ince** — iş mantığını `services/` katmanına devreder.
  Bu "ince controller" deseni test ve bakımı kolaylaştırır.

```python
69  @app.post("/api/devices/{bin_id}/state-change")
70  def post_state_change(bin_id: str, payload: StateChangeIn, db: Session = Depends(get_db)):
75      try:
76          log_state_change(db, bin_id, payload)
77      except Exception as exc:
78          raise HTTPException(status_code=500, detail=str(exc)) from exc
```

- **Satır 69-79:** ESP32'nin vurduğu endpoint. Path'teki `{bin_id}` + gövdedeki `payload`
  birlikte `log_state_change`'e gider (Bölüm 6).

> ### 🔍 Nasıl aratmalıyım?
> - **"Uygulama açılışta ne yapıyor?"** → `grep -n "lifespan\|load_bins" backend/app/main.py`
> - **"ESP32 hangi URL'e vuruyor?"** → `grep -rn "state-change\|heartbeat" backend frontend ESP32-Sensor`

---

## 6. Bin Servisi — `bins_service.py`

[backend/app/services/bins_service.py](../backend/app/services/bins_service.py) — bin CRUD + IoT verisi işleme.

**DB hatası → CSV fallback:**

```python
42  def fetch_bins(db: Session) -> list[dict]:
43      query = text("""SELECT bin_id, latitude AS lat, ... FROM bins ORDER BY bin_id""")
62      try:
63          rows = db.execute(query).mappings().all()
64          return [dict(row) for row in rows]
65      except SQLAlchemyError:
66          return _load_bins_from_csv()
```

- **Satır 62-66:** DB erişilemezse `_load_bins_from_csv()` (satır 20) devreye girer — backend
  veritabanı olmadan da harita gösterebilir. Demo dayanıklılığı için tasarlanmış.

**`log_state_change` — ESP32 ölçümünü işleyen ana fonksiyon (satır 107):**

```python
114      telemetry_query = text("""
115          INSERT INTO telemetry (bin_id, enum_state, raw_distance_cm)
116          VALUES (:bin_id, :enum_state, :raw_distance_cm)
117      """)
```
- **Satır 114-128:** Önce ham ölçüm `telemetry` tablosuna işlenir (geçmiş/anomali için).

```python
144      update_query = text("""
145          UPDATE bins SET
148              last_enum_transition = CASE
149                  WHEN fill_level IS NULL OR fill_level = :new_fill_level THEN last_enum_transition
150                  ELSE fill_level || '->' || :new_fill_level   -- "EMPTY->FULL"
151              END,
...
156              fill_level = :new_fill_level,
157              is_active = TRUE,
158              last_seen_at = COALESCE(:event_timestamp, NOW()),
```
- **Satır 148-151:** Akıllı CASE mantığı — seviye **değiştiyse** geçiş özeti (`"EMPTY->FULL"`)
  yazılır, değişmediyse eski değer korunur. Gereksiz "kendi kendine geçiş" loglanmaz.

```python
178      try:
182          check_overflow_risk(db, bin_id, new_level_enum, ..., previous_level_value)
190          check_sensor_error_flag(db, bin_id, new_level_enum, ...)
192          check_sensor_fixed_value_error(db, bin_id)
194          check_fill_anomaly(db, bin_id)
195      except Exception:
197          pass   # anomali tespiti state-change'i ASLA bozmamalı
200      db.commit()
```
- **Satır 178-197:** 4 anomali kuralı çalıştırılır (Bölüm 7). Hepsi `try/except` içinde —
  bir anomali hatası ana akışı düşürmesin diye **bilinçli olarak yutulur**.

```python
204      try:
205          from ..simulation_engine import engine
206          engine.inject_sensor_reading(bin_id=bin_id, enum_state=..., median_distance_cm=...)
207      except Exception:
208          pass
```
- **Satır 204-212:** Gerçek sensör verisi **canlı simülasyona da enjekte edilir**
  (Bölüm 11, `inject_sensor_reading`). Lazy import (satır 205) döngüsel bağımlılığı kırar.

> ### 🔍 Nasıl aratmalıyım?
> - **"Sensör verisi DB'ye nasıl yazılıyor?"** → `grep -n "def log_state_change" backend/app/services/bins_service.py`
> - **"CSV fallback ne zaman devreye giriyor?"** → `grep -n "_load_bins_from_csv\|SQLAlchemyError" backend/app/services/bins_service.py`

---

## 7. Anomali Servisi — `anomaly_service.py`

[backend/app/services/anomaly_service.py](../backend/app/services/anomaly_service.py) 4 kural-tabanlı tespitçi içerir.

**Ortak yazıcı (satır 12):**
```python
26      insert_query = text("""INSERT INTO event_log (bin_id, event_type, details) VALUES (...)""")
38      update_summary_query = text("""UPDATE bins SET last_event_type = ..., last_event_at = ...""")
```
- Hem `event_log`'a satır ekler hem `bins` özet alanlarını günceller.

**Kural 1 — Taşma riski (satır 58):**
```python
72      if new_level != FillLevelEnum.CRITICAL_FULL:
73          return
77      if previous_level == FillLevelEnum.CRITICAL_FULL.value:
78          return   # zaten kritikti → spam loglama
```
- **Satır 72-78:** Sadece **başka bir durumdan** `CRITICAL_FULL`'a **geçişte** tetiklenir.

**Kural 3 — Takılı sensör değeri (satır 110):**
```python
123      query = text("""SELECT raw_distance_cm FROM telemetry
                          WHERE bin_id = :bin_id ... ORDER BY created_at DESC LIMIT :limit""")
143      min_val = min(distances)
144      max_val = max(distances)
146      if max_val - min_val <= tolerance_cm:    # son 3 ölçüm neredeyse aynı → sensör takılmış
152          log_anomaly_event(db, bin_id, AnomalyType.SENSOR_FIXED_VALUE_ERROR, details)
```
- **Satır 143-146:** Son 3 ölçüm `0.2 cm` toleransı içindeyse sensör donmuş kabul edilir.

**Kural 4 — Şüpheli dolum paterni (satır 155):**
```python
180      if not (newest["enum_state"] == FillLevelEnum.EMPTY.value
181              and mid["enum_state"] == FillLevelEnum.CRITICAL_FULL.value
182              and oldest["enum_state"] == FillLevelEnum.EMPTY.value):
185          return
194      if end_time - start_time <= timedelta(minutes=time_window_minutes):  # 15 dk içinde
199          log_anomaly_event(db, bin_id, AnomalyType.FILL_ANOMALY, details)
```
- **Satır 180-194:** `EMPTY→CRITICAL_FULL→EMPTY` paterni 15 dk içinde olduysa **fiziksel
  olarak imkansız hızda** dolup boşalmış → muhtemel sahte/hatalı veri.

> ### 🔍 Nasıl aratmalıyım?
> - **"Kaç anomali kuralı var?"** → `grep -n "^def check_" backend/app/services/anomaly_service.py`
> - **"Bir anomali tipi nerede üretiliyor?"** (ör. FILL_ANOMALY) → `grep -rn "FILL_ANOMALY" backend/app`

---

## 8. DPET Algoritması — `dpet.py`

[backend/app/dpet.py](../backend/app/dpet.py) **projenin akademik çekirdeği**: 6 katmanlı dinamik
dispatch. Dosya başındaki docstring (satır 1-18) tüm katmanları özetler.

**Katman 1 — Trafik modeli (satır 75):**
```python
71  _RUSH_HOURS = frozenset({7, 8, 9, 17, 18, 19})
72  _PEAK_HOURS = frozenset({6, 10, 16, 20})
75  def traffic_score(hour: int) -> float:
77      if hour in _RUSH_HOURS: return 0.80
79      if hour in _PEAK_HOURS: return 0.50
81      return 0.20
```
- Saate göre 0-1 trafik skoru. Yoğun saatte algoritma daha seçici davranır.

**Katman 2 — Bin skorlama (satır 122):** 5 bileşenli ağırlıklı skor.
```python
88  _W_FILL = 0.40; _W_ETF = 0.35; _W_PROXIMITY = 0.05; _W_TRAFFIC = 0.12; _W_DENSITY = 0.08
138      fill_urgency = (fill_pct / 100.0) ** 2   # kare → kritik bin'ler çok daha yüksek
139      if fill_pct >= 85.0:
140          boost = (fill_pct - 85.0) / 15.0     # 85→100 arası ekstra ivme
141          fill_urgency += boost * (1.0 - fill_urgency)
142      etf          = _etf_hours(fill_pct, fill_rate)
143      etf_urgency  = max(0.0, 1.0 - etf / _ETF_HORIZON)   # taşmaya yakınsa yüksek
147      return (_W_FILL*fill_urgency + _W_ETF*etf_urgency + ... )
```
- **Satır 138:** Doluluk **karesi** alınır → %90 dolu bir bin, %45 dolunun 4 katı aciliyet.
- **ETF** = Estimated Time to Full (taşmaya kalan saat). `_etf_hours` (satır 100) bunu hesaplar.

**Katman 3 — Bin seçimi (satır 177):**
```python
191      min_fill = _MIN_FILL_RUSH if traffic > _RUSH_THR else _MIN_FILL_NORMAL
199          is_emergency       = b.fill_pct >= _EMERGENCY_FILL    # %88+ → her zaman al
200          is_etf_urgent      = etf <= ETF_LEAD_TIME             # ≤3 saat → her zaman al
201          is_above_threshold = b.fill_pct >= min_fill
202          if not (is_emergency or is_etf_urgent or is_above_threshold):
203              continue
215      result.sort(key=lambda x: x.score, reverse=True)
216      return result[:max_stops]
```
- **Satır 199-203:** Üç "geçiş kapısı" — biri bile doğruysa bin aday olur.

**Katman 4 — Rota kurma: NN + kapasite + 2-opt (satır 258):**
```python
242  def _trim_by_capacity(nn_ordered):
249      for ss in nn_ordered:
250          load = (ss.fill_pct / 100.0) * BIN_VOLUME_FRACTION
251          if used + load > TRUCK_CAPACITY + 1e-9:
252              break    # kamyon doldu → kalanı bir sonraki kamyona
270      nn_ordered = _nn_route(scored, depot_lat, depot_lon)
271      trimmed    = _trim_by_capacity(nn_ordered)
273      return _full_2opt(stops, depot_lat, depot_lon)
```

**Ağırlık-duyarlı 2-opt (satır 286, 309) — projenin en ince fikri:**
```python
294      Formül: cost_i = dist_i × (1 + FUEL_WEIGHT_FACTOR × i/n)
300      for i in range(n - 1):
302          w_factor = (i + 1) / n            # kamyon doldukça ağırlaşır
303          cost    += dist * (1.0 + FUEL_WEIGHT_FACTOR * w_factor)
```
- **Satır 309 `_full_2opt`:** Klasik 2-opt km minimize eder; burada **yakıt** minimize edilir.
  Kamyon doldukça ağırlaştığı için algoritma "ağır yükle kısa, hafif yükle uzun bacak" tercih eder.

**Katman 6 — Dispatcher (satır 356):**
```python
377      available_slots = max_fleet - active_truck_count
378      if available_slots <= 0: return []
391      if len(selected) < min_dispatch and not has_any_urgent:
392          return []                # acil yoksa az bin için kamyon çıkarma
405          eff = route_efficiency(route, depot_lat, depot_lon)
406          if eff < _MIN_ROUTE_EFFICIENCY and not _chunk_is_urgent(chunk):
407              continue             # verimsiz + acilsiz rota → atla
```
- **Satır 391-392:** "Boşa sefer yapma" kuralı — DPET'in `fixed`'e karşı kazanç kaynağı.

> ### 🔍 Nasıl aratmalıyım?
> - **"Skor ağırlıkları nerede?"** → `grep -n "_W_" backend/app/dpet.py`
> - **"Dispatch kararı nasıl veriliyor?"** → `grep -n "def dpet_dispatch" backend/app/dpet.py`
> - **"ETF nasıl hesaplanıyor?"** → `grep -rn "_etf_hours\|def.*etf" backend/app`

---

## 9. Çevre/Talep Modeli — `environment.py`

[backend/app/environment.py](../backend/app/environment.py) simülasyona **gerçekçi kentsel dolum
dinamiği** katar (Phase 1). 5 katman; dışarıya sadece 2 fonksiyon açar.

**Katman 1 — District tipleri (satır 26):**
```python
26  class DistrictType(str, Enum):
27      RESIDENTIAL = "residential"   # akşam piki
28      OFFICE      = "office"        # sabah/öğle piki
29      MALL        = "mall"; UNIVERSITY = "university"; TOURIST = "tourist"
```

**Katman 2 — Saatlik profiller (satır 40):** Her district için 24 değerli dolum çarpanı.
```python
43      DistrictType.RESIDENTIAL: [
44          0.2, 0.2, 0.2, ...,        # 00-05 gece sakin
47          1.8, 2.0, 1.7, 1.3, 0.8, 0.4,   # 18-23 akşam piki (aile evde)
48      ],
```
- **Satır 47:** Konut bölgesi akşam 19:00'da `2.0×` hızlanır — gerçek gözlemi yansıtır.

**Katman 3 — Gürültü (satır 97):**
```python
97  def apply_noise(value: float) -> float:
99      noise_factor = 1.0 + random.gauss(0.0, _NOISE_STD)   # ±%10 Gaussian
100      return max(0.0, value * noise_factor)
```
- Determinizmi kırar → her simülasyon biraz farklı, gerçekçi.

**Katman 4 — Event sistemi (satır 150):** Konser/maç/festival geçici talep patlamaları.
```python
167      def tick(self, sim_s: float) -> Event | None:
172          self._cleanup(sim_s)                  # süresi dolanları sil
173          if sim_s >= self._next_spawn_s:
174              return self._spawn(sim_s)         # yeni event üret
```

**Katman 5 — Public API: `effective_fill_rate` (satır 256):**
```python
274      h_mult = hourly_multiplier(district, hour)
278      for ev in events:
279          if ev.affects(district):
280              e_mult = max(e_mult, ev.multiplier)   # en güçlü event çarpanı
282      rate = base_rate * h_mult * e_mult
283      return apply_noise(rate)
```
- **Satır 282:** Etkin hız = `temel × saat çarpanı × event çarpanı × gürültü`.
  Motor her tick'te bunu çağırır (Bölüm 11, `_job_fill`).

> ### 🔍 Nasıl aratmalıyım?
> - **"Bir district saatlik nasıl dolar?"** → `grep -n "HOURLY_PROFILES" backend/app/environment.py`
> - **"Etkin dolum hızı formülü?"** → `grep -n "def effective_fill_rate" backend/app/environment.py`
> - **"Region → district eşleştirmesi?"** → `grep -n "_REGION_KEYWORDS\|def assign_district" backend/app/environment.py`

---

## 10. Tahmin + Zone — `predictor.py`

[backend/app/predictor.py](../backend/app/predictor.py) iki iş yapar: **(1) K-means coğrafi
zone ataması**, **(2) gözlemden dolum hızı öğrenme + ETF tahmini**.

**Zone ataması — K-means++ (satır 65):**
```python
78      centroids = [random.choice(points)[1:]]    # K-means++ başlangıcı
79      while len(centroids) < n:
80          dists = [min(_geo_dist(p, c) for c in centroids) for p in points]
84          r = random.random() * total            # uzak noktalar daha olası
94      for _ in range(KMEANS_ITERATIONS):         # Lloyd iterasyonları
```
- **Satır 78-90:** K-means++ → başlangıç merkezleri birbirinden uzak seçilir (daha iyi kümeler).
- **Satır 94-113:** 25 Lloyd iterasyonuyla merkezler oturur. Startup'ta **bir kez** çalışır.

**Öğrenme — gözlemden hız (satır 129):**
```python
137      if event == "EMPTIED":
138          self._last_emptied[bin_id] = sim_s          # döngü başlangıcı
139      elif event == "OVERFLOW":
141          if last is not None and sim_s > last:
142              cycle_s = sim_s - last                  # bir dolum döngüsü süresi
143              cycles  = self._cycles.setdefault(bin_id, [])
144              cycles.append(cycle_s)
145              if len(cycles) > MAX_CYCLES: cycles.pop(0)   # son 8 döngü (rolling)
```
- **Satır 137-145:** `EMPTIED→OVERFLOW` arası süre = bir gerçek dolum döngüsü. Son 8 döngünün
  ortalamasından hız öğrenilir → konfigüre edilen statik `fill_rate`'in yerini alır.

```python
150  def predicted_fill_rate_h(self, bin_id, fallback_rate):
156      if len(cycles) < 2:
157          return fallback_rate         # < 2 gözlem → statik değere düş
158      avg_s = sum(cycles) / len(cycles)
159      return 100.0 / (avg_s / 3600.0)  # döngü süresinden %/saat
```

**Zone sorguları** — motorun dispatch katmanlarını besler:
- `urgent_zone_bins` (satır 209) → ETF ≤ eşik olan bin'leri zone bazında grupla (Tier-1).
- `coverage_zone_bins` (satır 236) → bir zone'daki dolu bin'ler (Tier-2 coverage).
- `adaptive_coverage_interval_s` (satır 254) → hızlı zone sık, yavaş zone seyrek ziyaret.

> ### 🔍 Nasıl aratmalıyım?
> - **"Zone'lar nasıl atanıyor?"** → `grep -n "def assign_zones" backend/app/predictor.py`
> - **"Dolum hızı nasıl öğreniliyor?"** → `grep -n "def record_event\|def predicted_fill_rate" backend/app/predictor.py`
> - **"K-means kaç zone?"** → `grep -n "N_ZONES\|KMEANS" backend/app/predictor.py`

---

## 11. Simülasyon Motoru — `simulation_engine.py`

[backend/app/simulation_engine.py](../backend/app/simulation_engine.py) — **1233 satır, projenin
en büyük dosyası**. Tüm modülleri (dpet, environment, predictor) orkestre eder.
Docstring (satır 1-16) iki dünya modelini özetler.

### 11.1 Sabitler ve veri sınıfları

```python
44  FILL_RATE_RANGES: dict[str, tuple[float, float]] = {
45      "A": (12.0, 16.0),  # hızlı: 6-8 sim saatte dolar
46      "B": (4.0,  8.0),   # orta
47      "C": (0.5,  1.5),   # yavaş
48  }
63  MAX_FLEET_SIZE = 12       # her dünya için maks aktif kamyon
```
- **Satır 44-48:** Bin etiketine göre dolum hızı aralıkları. A-etiketi bin'ler DPET'in avantajını
  belirginleştirir (sık dolar → erken yakalama önemli).

```python
108  @dataclass
109  class BinState:                  # bir kovanın canlı durumu
118      fill_pct: float      = 0.0
121      anomaly_end_sim_s: float = 0.0
122      overflow_start_s: float  = -1.0   # ilk %100 anı (aging için)
125      def refresh_status(self) -> None:
128          if self.fill_pct >= CRITICAL_THRESHOLD: self.status = "CRITICAL_FULL"
130          elif self.fill_pct >= FULL_THRESHOLD:   self.status = "FULL"
132          else:                                   self.status = "EMPTY"
```
- **Satır 125-132:** `fill_pct` → durum string'i dönüşümü. Anomali varsa dokunmaz (satır 126).

```python
143  @dataclass
144  class TruckRoute:                # bir kamyonun canlı durumu + rotası
163      capacity_used: float = 0.0   # [0,1] normalize doluluk
```

### 11.2 Yardımcı fonksiyonlar

```python
168  def _haversine_km(lat1, lon1, lat2, lon2) -> float:   # iki nokta arası km
178  def _nearest_neighbor(bins, from_lat, from_lon):       # NN sıralama
192  def _two_opt_route(stops, depot_lat, depot_lon):       # 2-opt iyileştirme
221  def _weighted_fuel(stops, depot_lat, depot_lon):       # ağırlık-duyarlı yakıt
```

`_weighted_fuel` (satır 221) — KPI hesabının temeli:
```python
233      for i, stop in enumerate(stops):
235          w_factor = i / max(n, 1)                       # 0→1 doldukça
236          fuel_km  = FUEL_PER_KM * (1 + WEIGHT_MULTIPLIER * w_factor)
238          total_fuel += dist * fuel_km
242      dist_ret = _haversine_km(prev_lat, prev_lon, depot_lat, depot_lon)
244      total_fuel += dist_ret * FUEL_PER_KM * (1 + WEIGHT_MULTIPLIER)  # dönüş: tam dolu
```

`_insertion_km` (satır 270) — bir bin'i mevcut rotaya **en ucuz** nereye eklerim?
```python
302          extra = (_haversine_km(_pl, _plo, new.lat, new.lon)
303                   + _haversine_km(new.lat, new.lon, stop.lat, stop.lon)
304                   - _haversine_km(_pl, _plo, stop.lat, stop.lon))    # ekleme maliyeti
```
- Bu, "fırsatçı toplama" (corridor) ve "acil ekleme" özelliklerini mümkün kılar.

### 11.3 Ana döngü

```python
564  TICK_REAL_S = 0.2
566  async def _loop(self) -> None:
567      while self.is_running:
568          self._sim_s += self.TICK_REAL_S * self.speed_multiplier   # sanal zaman ilerlet
569          self._job_events()        # event üret/temizle
570          self._job_fill()          # bin'leri doldur
571          self._job_dispatch_algo() # DPET dispatch
572          self._job_dispatch_fixed()# sabit rota dispatch
573          self._job_anomaly()       # rastgele anomali
574          self._heal_anomalies()    # süresi dolan anomalileri iyileştir
575          self._advance_trucks()    # kamyonları hareket ettir
576          await asyncio.sleep(self.TICK_REAL_S)
```
- **Satır 568:** Gerçek 0.2 sn = `speed_multiplier × 0.2` sanal saniye. `3600×` hızda her gerçek
  saniye ≈ 12 sanal dakika.
- **Satır 569-575:** Her tick 7 işi sırayla çalıştırır. Bu sıralama önemli (önce doldur, sonra dağıt).

### 11.4 FillJob — dolum (satır 580)

```python
581      if self._sim_s - self._last_fill_s < FILL_JOB_INTERVAL_S:   # her 1 sim saat
582          return
588      for world, kpis, world_name in ((self.algo_bins, ...), (self.fixed_bins, ...)):
592          for b in world.values():
597              rate = effective_fill_rate(b.fill_rate, b.district_type, hour, events)  # Phase 1
600              b.fill_pct = min(100.0, b.fill_pct + rate)
602              if b.fill_pct >= 100.0:
603                  kpis["overflow_events"] += 1
604                  if old_pct < 100.0:
605                      kpis["overflow_count"] += 1      # yeni taşma olayı
```
- **Satır 588:** **İki dünya da aynı `effective_fill_rate` ile** doldurulur → adil karşılaştırma.
- **Satır 603 vs 605:** `overflow_events` = %100'de kalınan her tick (bin-saat); `overflow_count`
  = ayrı taşma olayı sayısı. KPI panosunda ikisi farklı gösterilir.

### 11.5 Gerçek sensör enjeksiyonu (satır 613)

`inject_sensor_reading` — `bins_service.log_state_change` (Bölüm 6) buradan çağırır:
```python
635      if enum_state == "SENSOR_ERROR":               # her iki dünyada anomali penceresi aç
643          b.is_anomaly = True; b.anomaly_end_sim_s = end_s
648      if median_distance_cm is not None and median_distance_cm > 0:
649          effective = max(0.0, median_distance_cm - SENSOR_OFFSET_CM)   # ESP32 ile aynı formül
652          fill_pct  = (filled / SENSOR_BIN_HEIGHT_CM) * 100.0
674          if old_pct >= FULL_THRESHOLD and fill_pct < FULL_THRESHOLD:
675              b.empty(self._sim_s)                    # yüksekten boşa düşüş → boşaltıldı
676              self._append_history("EMPTIED", b, world_name)
```
- **Satır 649-652:** Fill yüzdesi **ESP32 firmware'iyle birebir aynı geometriyle** hesaplanır
  (`SENSOR_OFFSET_CM`, `SENSOR_BIN_HEIGHT_CM` sabitleri satır 92-93'te firmware ile eşleşir).

### 11.6 DPET DispatchJob — 4 katmanlı (satır 788)

Bu fonksiyon `dpet.py`'yi çağırır ama etrafına **4 öncelik katmanı** sarar:

```python
794      claimed   = self._active_stop_bin_ids(self.algo_trucks)   # zaten rotada olanları çıkar
795      available = {b.bin_id: b for b in self.algo_bins.values() if b.bin_id not in claimed}
798      urgent = [b for b in available.values() if b.fill_pct >= EXTENSION_FILL_THRESHOLD ...]
800      extended_ids = self._try_extend_truck(urgent) ...    # önce mevcut kamyona ekle
804          corridor = self._corridor_bins(available, ...)   # rota üstündeki bin'leri topla
```

```python
842      # ── Tier 0 — Priority Aging (ekstra kamyon) ──
845      aged_bins = [b for b in available.values()
846                   if b.overflow_start_s >= 0
847                   and self._sim_s - b.overflow_start_s >= AGING_THRESHOLD_S ...]  # 4 saat bekleyen

865      # ── Tier 1 — Acil zone (ETF ≤ 2 saat) ──
866      urgent_zones = self._predictor.urgent_zone_bins(available, URGENT_ZONE_ETF_H, ...)

872      # ── Tier 2 — Coverage Rotation (adaptif interval) ──
875      for zone_id in range(self._predictor.n_zones()):
881          adaptive_interval = self._predictor.adaptive_coverage_interval_s(...)
884          if self._sim_s - last_visit < adaptive_interval: continue

895      # ── Fallback — hiç dispatch yoksa ve ≥95% bin varsa ──
```
- **Mantık:** Önce mevcut kamyonları kullan (ekleme/koridor), sonra acil zone, sonra düzenli
  kapsama, en son çare olarak acil fallback. Bu katmanlama "boşa sefer"i minimize eder.

### 11.7 Fixed DispatchJob (satır 917) ve sabit rota ön-hesabı

```python
499  def _precompute_fixed_routes(self) -> None:
510      def _angle_from_depot(b):
511          return math.atan2(b.lon - self.depot_lon, b.lat - self.depot_lat)
513      all_bins = sorted(self.fixed_bins.values(), key=_angle_from_depot)   # Sweep heuristic
515      for i in range(0, len(all_bins), FIXED_ROUTE_SIZE):                  # 20'lik dilimler
```
- **Satır 499-519:** Gillett & Miller (1974) **Sweep algoritması** — depot'tan açıya göre
  sıralayıp 20'lik radyal dilimlere böler. Belediyelerin gerçek "yönlü rota" pratiğini taklit eder.

```python
917  def _job_dispatch_fixed(self):
919      if vc.hour < FIXED_DISPATCH_HOUR: return       # her gün 06:00'dan önce çıkma
921      day_key = (vc.year, vc.month, vc.day)
922      if self._last_fixed_day_key == day_key: return # günde bir kez
928      for _ in range(min(MAX_FLEET_SIZE, len(self._fixed_routes))):
929          self._dispatch_next_fixed_route()
```

### 11.8 Kamyon hareketi — `_step_truck` (satır 1017)

State machine: `en_route → servicing → en_route ... → returning → done`.
```python
1018      if t.status == "en_route":
1019          if s >= t.leg_end_sim_s:               # bacağı tamamladı → durağa vardı
1025              t.status = "servicing"
1030              bin_load = (b.fill_pct / 100.0) * BIN_VOLUME_FRACTION
1031              t.capacity_used = min(TRUCK_CAPACITY, t.capacity_used + bin_load)
1032              self._append_history("EMPTIED", b, world_name)
1036              b.empty(self._sim_s)               # bin boşaltıldı
1040              t.lat = t.from_lat + (t.to_lat - t.from_lat) * t.progress   # ara konum (animasyon)
```
- **Satır 1040-1041:** En_route ararken `progress` (0-1) ile lineer interpolasyon → frontend
  kamyonun yolda akıcı hareketini bu sayede çizer.

### 11.9 History + Predictor besleme (satır 1095)

```python
1095  def _append_history(self, event, b, world):
1108      if world == "algo":
1109          self._predictor.record_event(event, b.bin_id, self._sim_s)  # sadece algo öğrensin
```
- **Satır 1109:** Predictor **yalnızca algo dünyasından** beslenir (fixed dünya öğrenmez,
  sabit rotalarla çalışır).

### 11.10 Snapshot'lar — API çıktısı (satır 1192)

```python
1192  def state_snapshot(self) -> dict:        # GET /live-state → bin + kamyon konumları
1215  def kpis_snapshot(self) -> dict:         # GET /live-kpis → KPI + tasarruf
1223          "savings": {
1224              "co2_kg": round(f["co2_kg"] - a["co2_kg"], 1),   # fixed - algo = tasarruf
```
- **Satır 1223-1227:** Tasarruf = `fixed KPI − algo KPI`. Frontend bu farkı "ALGORİTMA TASARRUFU"
  şeridinde gösterir.

```python
1233  engine = SimulationEngine()    # modül seviyesinde singleton
```

> ### 🔍 Nasıl aratmalıyım?
> - **"Tick döngüsünde ne çalışıyor?"** → `grep -n "def _job_\|def _loop\|def _advance" backend/app/simulation_engine.py`
> - **"Bir KPI nasıl hesaplanıyor?"** (ör. co2) → `grep -n "co2_kg\|CO2_PER_KM" backend/app/simulation_engine.py`
> - **"Kamyon durumları neler?"** → `grep -n "status ==\|t.status =" backend/app/simulation_engine.py`
> - **"Dispatch katmanları nerede?"** → `grep -n "Tier 0\|Tier 1\|Tier 2\|Fallback" backend/app/simulation_engine.py`

---

## 12. Simülasyon Router — `routers/simulation.py`

[backend/app/routers/simulation.py](../backend/app/routers/simulation.py) — motoru web'e açan ince katman.
Docstring (satır 1-12) tüm endpoint'leri listeler.

```python
24  @router.post("/start")
25  async def start_simulation():
26      await engine.start()                       # asyncio task başlatır
36  @router.post("/reset")
38      was_running = engine.is_running
39      await engine.stop(); engine.reset()
41      if was_running: await engine.start()       # çalışıyorduysa yeniden başlat
46  @router.patch("/speed")
48      if multiplier not in valid: return {"error": ...}
51      engine.speed_multiplier = multiplier
```

```python
70  @router.get("/export-csv")
72      history = engine.fill_history
79      writer = csv.DictWriter(output, fieldnames=fieldnames)
84      return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", ...)
```
- **Satır 70-88:** `fill_history`'yi CSV olarak indirir — rapor/analiz için ham veri çıkışı.

> ### 🔍 Nasıl aratmalıyım?
> - **"Simülasyon endpoint'leri neler?"** → `grep -n "@router" backend/app/routers/simulation.py`
> - **"Hız seçenekleri nerede?"** → `grep -rn "SPEED_OPTIONS" backend/app`

---

## 13. ESP32 Firmware — `ESP32-Sensor.ino`

[ESP32-Sensor/ESP32-Sensor.ino](../ESP32-Sensor/ESP32-Sensor.ino) — HC-SR04 ultrasonik sensörle
gerçek kova ölçümü yapıp backend'e gönderen tek-dosya firmware.

**Geometri sabitleri — backend ile eşleşmeli (satır 13-14):**
```cpp
13  const float BIN_HEIGHT_CM   = 100.0f;   // simulation_engine SENSOR_BIN_HEIGHT_CM ile aynı
14  const float SENSOR_OFFSET_CM = 3.0f;     // simulation_engine SENSOR_OFFSET_CM ile aynı
```

**Medyan ölçüm — gürültü filtresi (satır 95):**
```cpp
101    for (int i = 0; i < numSamples; ++i) {       // 10 örnek al
102      float d = measureDistanceOnce(timeoutMicros);
103      if (!isnan(d)) samples[validCount++] = d;
113    qsort(samples, validCount, sizeof(float), compareFloat);   // sırala
116    if (validCount % 2 == 1) median = samples[validCount / 2];  // medyan
```
- 10 ölçümün medyanı → tek tük hatalı okumaya dayanıklı.

**Mesafe → doluluk yüzdesi (satır 127) — backend formülünün aynısı:**
```cpp
130    float effectiveDistance = measuredDistanceCm - SENSOR_OFFSET_CM;
133    float filledHeight = BIN_HEIGHT_CM - effectiveDistance;
137    float fillPct = (filledHeight / BIN_HEIGHT_CM) * 100.0f;
```

**Enum eşikleri (satır 144):**
```cpp
154    if (fillPct < 60.0f)      return FillLevel::EMPTY;
156    else if (fillPct < 90.0f) return FillLevel::FULL;
158    else                      return FillLevel::CRITICAL_FULL;
```

**Akıllı gönderim mantığı — pil tasarrufu (satır 288):**
```cpp
290    bool firstBoot      = (rtc_lastLevelInt == -1);
291    bool levelChanged   = (!firstBoot && currentLevelInt != rtc_lastLevelInt);
292    bool forceHeartbeat = (rtc_wakeCounter >= HEARTBEAT_WAKE_INTERVAL);  // 8 uyanma
303    bool needWifi = firstBoot || levelChanged || forceHeartbeat;
310      if (firstBoot || levelChanged) ok = sendStateChange(medianDistance, currentLevel);
314      else if (forceHeartbeat)       ok = sendHeartbeat(currentLevel);
```
- **Satır 290-314:** WiFi sadece **gerektiğinde** açılır: enum değiştiyse `state-change`,
  8 saatte bir `heartbeat`. `RTC_DATA_ATTR` (satır 51-52) deep-sleep boyunca state'i korur.
- **Satır 346 `goToDeepSleep()`** → 1 saat uyku → tüm pil ömrünü uzatır.

> ### 🔍 Nasıl aratmalıyım?
> - **"Doluluk yüzdesi nasıl hesaplanıyor?"** → `grep -n "computeFillPercentage\|fillPct" ESP32-Sensor/ESP32-Sensor.ino`
> - **"Backend'e ne zaman veri gönderiliyor?"** → `grep -n "needWifi\|sendStateChange\|sendHeartbeat" ESP32-Sensor/ESP32-Sensor.ino`
> - **"Sensör geometrisi backend'le eşleşiyor mu?"** → `grep -rn "BIN_HEIGHT_CM\|SENSOR_OFFSET" backend ESP32-Sensor`

---

## 14. Frontend API Katmanı — `api.js`

[frontend/src/services/api.js](../frontend/src/services/api.js) — tüm HTTP çağrılarının tek noktası.

```js
 3  const api = axios.create({
 4    baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000'
 5  })
12  export const getBins      = ()            => api.get('/api/bins')
23  export const startSim     = ()            => api.post('/api/simulation/start')
27  export const getLiveState = ()            => api.get('/api/simulation/live-state')
```
- **Satır 3-5:** Tek bir axios instance; `baseURL` env'den. Tüm bileşenler bu fonksiyonları
  import eder → endpoint string'leri tek yerde toplanır (bakım kolaylığı).

> ### 🔍 Nasıl aratmalıyım?
> - **"Frontend hangi endpoint'leri çağırıyor?"** → `grep -n "api.get\|api.post\|api.patch" frontend/src/services/api.js`
> - **"Bir API fonksiyonu nerede kullanılıyor?"** (ör. getLiveState) → `grep -rn "getLiveState" frontend/src`

---

## 15. Frontend Ana Harita — `App.jsx` + `MapView.jsx`

### `App.jsx` — statik bin haritası + rota planlama
[frontend/src/App.jsx](../frontend/src/App.jsx)

```jsx
22    useEffect(() => {
26        const [binsResponse, summaryResponse] = await Promise.all([getBins(), getSummary()])
27        setBins(binsResponse.data)
35      load()
36    }, [])                              // [] → sadece mount'ta bir kez çalışır
```
- **Satır 22-36:** Sayfa açılışında bin'ler + özet paralel çekilir (`Promise.all`).

```jsx
48    const handlePlanRoute = async () => {
49      const priorityBins = bins.filter((b) => b.status === 'CRITICAL_FULL' || b.status === 'FULL')
62        const waypoints = priorityBins.slice(0, 49).map((b) => ({ lat: b.lat, lon: b.lon }))
66        const coords = result.geometry.coordinates.map(([lon, lat]) => [lat, lon])  // GeoJSON→Leaflet
```
- **Satır 49:** Sadece FULL/CRITICAL bin'ler için rota planlanır.
- **Satır 66:** **Kritik dönüşüm** — GeoJSON `[lon,lat]` sırasını Leaflet'in beklediği
  `[lat,lon]`'a çevirir. (Bu sıra hatası harita projelerinde en sık buglardan biridir.)

### `MapView.jsx` — Leaflet harita bileşeni
[frontend/src/components/MapView.jsx](../frontend/src/components/MapView.jsx)

```jsx
17    const iconsByStatus = useMemo(() => ({
19      OFFLINE: L.divIcon({ className: 'bin-marker-gray', ... }),
25      EMPTY:   L.divIcon({ className: 'bin-marker-empty', ... }),
37      CRITICAL_FULL: L.divIcon({ className: 'bin-marker-critical', ... }),
44    }), [])                            // useMemo → ikonlar bir kez oluşturulur
78      <MarkerClusterGroup chunkedLoading>   // yüzlerce bin'i kümeleyerek performans
```
- **Satır 17-44:** Durum → ikon eşlemesi `useMemo` ile cache'lenir (her render'da yeniden
  oluşmaz). **Satır 78:** Çok sayıda marker kümelenerek (`MarkerClusterGroup`) çizilir.

> ### 🔍 Nasıl aratmalıyım?
> - **"Bin renkleri/ikonları nerede?"** → `grep -n "divIcon\|bin-marker" frontend/src/components/MapView.jsx`
> - **"Rota nasıl çiziliyor?"** → `grep -rn "Polyline\|routeSegments" frontend/src`
> - **"GeoJSON sırası nerede çevriliyor?"** → `grep -n "lon, lat\|lat, lon" frontend/src/App.jsx`

---

## 16. Frontend Simülasyon Paneli — `SimulationPage.jsx`

[frontend/src/components/SimulationPage.jsx](../frontend/src/components/SimulationPage.jsx) —
604 satır, iki dünyayı yan yana gösteren operasyon merkezi.

**Renk mantığı (satır 53):**
```jsx
53  function fillColor(status, fillPct) {
55    if (status === 'OFFLINE')      return '#6b7280'
56    if (status === 'SENSOR_ERROR') return '#a855f7'   // mor
57    if (status === 'CRITICAL_FULL')return '#ef4444'   // kırmızı
59    if (fillPct >= 30)             return '#eab308'    // sarı
60    return '#22c55e'                                   // yeşil
```

**Polling — canlı veri akışı (satır 455, 485):**
```jsx
36  const POLL_STATE_MS = 1_000; const POLL_KPIS_MS = 2_000; const POLL_ANOMALY_MS = 3_000
490    stateTimer.current   = setInterval(pollState,    POLL_STATE_MS)   // her 1 sn
491    kpiTimer.current     = setInterval(pollKPIs,     POLL_KPIS_MS)    // her 2 sn
494    return () => { clearInterval(stateTimer.current); ... }          // unmount'ta temizle
```
- **Satır 485-499:** 3 ayrı interval — konum (1 sn), KPI (2 sn), anomali (3 sn). Farklı
  frekanslar gereksiz ağ trafiğini azaltır. `return`'deki cleanup (satır 494) **kritik** —
  yoksa sayfadan çıkınca interval'lar sızar.

```jsx
455  const pollState = useCallback(async () => {
457      const { data } = await getLiveState()
458      setAlgoBins(data.algo_bins || [])
461      setFixedTrucks(data.fixed_trucks || [])
466    } catch { /* bağlantı hatası sessizce geçilir */ }
467  }, [])
```
- **Satır 455-467:** `state_snapshot` (Bölüm 11.10) yanıtını React state'lerine dağıtır.

**Verimlilik hesabı (satır 282):**
```jsx
282    const loadPerKm = kpis && kpis.distance_km > 0
283      ? Math.round((kpis.load_collected / kpis.distance_km) * 10) / 10 : null
287    const effRate = loadPerKm !== null ? Math.min(100, Math.round(loadPerKm / 0.8)) : ...
```
- **Satır 282-287:** "Yük/km" verimlilik metriği. Yorum (satır 278-281) bunun neden taşmadan
  **ayrı** gösterildiğini açıklar (iki farklı boyut, akademik doğruluk).

**İki dünya yan yana (satır 574):**
```jsx
575    <ColPanel title="ALGORİTMA KPI" accent="algo"  kpis={algoKPIs}  trucks={algoTrucks} ... />
586    <div className="opc-divider" />
587    <ColPanel title="SABİT ROTA"   accent="fixed" kpis={fixedKPIs} trucks={fixedTrucks} ... />
```
- Aynı `ColPanel` bileşeni iki kez kullanılır → kod tekrarı yok, görsel simetri tam.

> ### 🔍 Nasıl aratmalıyım?
> - **"Canlı veri ne sıklıkla çekiliyor?"** → `grep -n "setInterval\|POLL_" frontend/src/components/SimulationPage.jsx`
> - **"Verimlilik skoru nasıl hesaplanıyor?"** → `grep -n "loadPerKm\|effRate" frontend/src/components/SimulationPage.jsx`
> - **"Kamyon/depo ikonu nasıl çiziliyor?"** → `grep -n "makeTruckIcon\|DEPOT_ICON" frontend/src/components/SimulationPage.jsx`

---

## 17. Uçtan Uca Akışlar

Kodu anlamanın en hızlı yolu, bir veriyi **baştan sona** takip etmektir.

### Akış A — Gerçek ESP32 ölçümü ekrana nasıl gelir?
1. `ESP32-Sensor.ino:270` → medyan mesafe ölç → enum belirle
2. `ESP32-Sensor.ino:311` → `POST /api/devices/{id}/state-change`
3. `main.py:69` → `post_state_change` → `bins_service.log_state_change` (`:107`)
4. `bins_service.py:114` DB'ye telemetry + bin update → `:182` anomali kontrolleri
5. `bins_service.py:206` → `engine.inject_sensor_reading` (`simulation_engine.py:613`)
6. Frontend `SimulationPage.jsx:457` her 1 sn `getLiveState` → harita güncellenir

### Akış B — DPET bir kamyonu nasıl yola çıkarır?
1. `simulation_engine.py:571` tick → `_job_dispatch_algo` (`:788`)
2. `:866` Tier-1 acil zone'lar → `predictor.urgent_zone_bins` (`predictor.py:209`)
3. `:828` → `dpet.dpet_dispatch` (`dpet.py:356`) → seç + rota kur (NN+2-opt)
4. `:838` → `_create_truck` (`:944`) → KPI'lar (`_weighted_fuel :221`) güncellenir
5. `:575` `_advance_trucks` → `_step_truck` (`:1017`) kamyonu hareket ettirir
6. `kpis_snapshot` (`:1215`) → `SimulationPage.jsx:469` panoya yansır

### Akış C — Tasarruf rakamı nasıl ortaya çıkar?
1. Her tick iki dünya da `_job_fill` (`:580`) ile **aynı hızda** dolar
2. `algo` DPET ile, `fixed` sabit rotalarla (`:917`) toplar → KPI'lar ayrışır
3. `kpis_snapshot:1223` → `savings = fixed − algo`
4. `SimulationPage.jsx:333` `SavingsStrip` → "ALGORİTMA TASARRUFU" gösterir

> ### 🔍 Genel arama ipuçları
> - **Bir fonksiyonun tanımı:** `grep -rn "def fonksiyon_adi" backend` (Python) / `grep -rn "function\|const .* =>" frontend` (JS)
> - **Bir fonksiyonun çağrıldığı yerler:** `grep -rn "fonksiyon_adi(" .`
> - **Bir sabitin tüm kullanımı:** `grep -rn "SABIT_ADI" backend frontend`
> - **VS Code'da:** `Ctrl+Shift+F` global arama, `F12` tanıma git, `Shift+F12` tüm referanslar
> - **Büyük dosyada gezinme:** `grep -n "^class \|^    def \|^def " dosya.py` → tüm sınıf/fonksiyon haritası

---

*Bu doküman kod ile birlikte güncel tutulmalıdır. Satır numaraları değişirse en güvenilir
referans, yukarıdaki "Nasıl aratmalıyım?" kutularındaki arama komutlarıdır.*
