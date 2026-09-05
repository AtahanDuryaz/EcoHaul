# Kod Detaylı Açıklama — Bölüm 1: API Katmanı ve Veritabanı

> Bu seri, EcoHaul'un **tüm kodunu** gerçek kod bloklarıyla, satır satır, "şu method
> şunu yapıyor / şurası önemli" tarzında açıklar.
>
> | Bölüm | İçerik |
> |-------|--------|
> | **1 (bu dosya)** | Veritabanı, DB bağlantısı, şemalar, FastAPI giriş, servisler |
> | 2 | DPET algoritması (`dpet.py`) |
> | 3 | Çevre/talep modeli + Tahmin/Zone (`environment.py`, `predictor.py`) |
> | 4 | Simülasyon motoru (`simulation_engine.py`) |
> | 5 | ESP32 firmware + tüm frontend |

---

## 1.1 Veritabanı Şeması — `init.sql`

Bu dosya PostgreSQL veritabanını sıfırdan kurar. PostGIS uzantısı sayesinde coğrafi
sorgular (mesafe, en yakın nokta) yapılabilir.

### `bins` tablosu — fiziksel kovaların ana kaydı

```sql
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS bins (
    id SERIAL PRIMARY KEY,
    bin_id TEXT UNIQUE NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    status TEXT NOT NULL DEFAULT 'OFFLINE',
    region TEXT NOT NULL,
    last_emptied_at TIMESTAMP NULL,
    -- IoT-related fields
    fill_level TEXT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_seen_at TIMESTAMP NULL,
    -- last enum transition summary, e.g. "EMPTY->FULL"
    last_enum_transition TEXT NULL,
    last_enum_change_at TIMESTAMP NULL,
    -- last anomaly summary (optional)
    last_event_type TEXT NULL,
    last_event_at TIMESTAMP NULL,
    geom GEOGRAPHY(Point, 4326) NOT NULL
);
```

**Önemli noktalar:**
- `id SERIAL PRIMARY KEY` → otomatik artan birincil anahtar (iç kullanım).
- `bin_id TEXT UNIQUE` → **iş anahtarı**. ESP32 ve frontend hep bunu kullanır (`WMS1872` gibi).
  `UNIQUE` olması aynı kovayı iki kez eklemeyi engeller.
- `status DEFAULT 'OFFLINE'` → bir kova ilk eklendiğinde henüz sensör verisi göndermediği
  için **çevrimdışı** kabul edilir.
- **IoT alanları** (`fill_level`, `is_active`, `last_seen_at`): ESP32'den gelen son durumu
  özetler. Yani bu tablo, her kovanın **anlık fotoğrafını** tutar; geçmiş ayrı tabloda.
- `last_enum_transition` → "EMPTY->FULL" gibi son durum geçişini metin olarak saklar. Hızlı
  bir bakışta "bu kova en son ne oldu?" sorusuna cevap verir.
- **`geom GEOGRAPHY(Point, 4326)` → ŞURASI ÖNEMLİ.** Bu PostGIS coğrafi tipi. `4326`
  = WGS84 koordinat sistemi (GPS'in kullandığı). Bu kolon sayesinde "şu konuma 500m
  yakındaki kovalar" gibi sorgular index destekli ve hızlı çalışır.

### `telemetry` tablosu — her ölçümün ham geçmişi

```sql
CREATE TABLE IF NOT EXISTS telemetry (
    id SERIAL PRIMARY KEY,
    bin_id TEXT NOT NULL,
    enum_state TEXT NOT NULL,
    raw_distance_cm DOUBLE PRECISION NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

`bins` tablosu sadece **son** durumu tutar; `telemetry` ise **her** ölçümü ayrı satır olarak
saklar. `raw_distance_cm` ham sensör mesafesidir — "takılı sensör" anomalisi tespiti tam
olarak bu kolonun geçmişine bakar (Bölüm 1.6'da göreceğiz).

### Indexler — performansın anahtarı

```sql
CREATE INDEX IF NOT EXISTS idx_bins_status ON bins(status);
CREATE INDEX IF NOT EXISTS idx_bins_region ON bins(region);
CREATE INDEX IF NOT EXISTS idx_bins_geom ON bins USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_telemetry_bin_id_created_at ON telemetry(bin_id, created_at DESC);
```

- `idx_bins_geom ... USING GIST(geom)` → **coğrafi index**. PostGIS coğrafi sorguları
  ancak GIST index ile hızlıdır.
- `idx_telemetry_bin_id_created_at ON telemetry(bin_id, created_at DESC)` → **birleşik index**.
  "Bir kovanın son 3 ölçümü" sorgusu (`WHERE bin_id=? ORDER BY created_at DESC LIMIT 3`)
  bu index ile tabloyu hiç taramadan çalışır. Anomali tespiti bunu çok sık yapar.

### Migrasyon güvenliği

```sql
ALTER TABLE bins ADD COLUMN IF NOT EXISTS last_event_type TEXT NULL;
ALTER TABLE bins ADD COLUMN IF NOT EXISTS last_event_at TIMESTAMP NULL;
```

`IF NOT EXISTS` sayesinde bu dosya **var olan** bir veritabanında tekrar çalıştırılsa bile
hata vermez; sadece eksik kolonları ekler. Yeni alanları sonradan eklerken veriyi kaybetmemek için.

### `event_log` tablosu — anomali kayıtları

```sql
CREATE TABLE IF NOT EXISTS event_log (
    id SERIAL PRIMARY KEY,
    bin_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    details TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

Tespit edilen her anomali (taşma riski, takılı sensör, vs.) buraya bir satır olarak yazılır.
`details` JSON metni olarak ek bilgi taşır.

---

## 1.2 Veritabanı Bağlantısı — `database.py`

Bu küçük dosya (24 satır) tüm SQLAlchemy altyapısını kurar.

```python
import os
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/ecohaul",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
```

**Satır satır:**
- `load_dotenv()` → proje kökündeki `.env` dosyasını okur, içindeki değişkenleri
  `os.getenv` ile erişilebilir yapar. Şifre/host gibi hassas bilgiyi koddan ayırır.
- `DATABASE_URL = os.getenv("DATABASE_URL", "...varsayılan...")` → **önce `.env`'e bakar**,
  bulamazsa ikinci parametredeki localhost varsayılanını kullanır. Bu sayede geliştirici
  hiçbir ayar yapmadan localhost'ta çalıştırabilir.
- `postgresql+psycopg://...` → bağlantı dizesi formatı: `sürücü://kullanıcı:şifre@host:port/veritabanı`.
- **`engine = create_engine(DATABASE_URL, pool_pre_ping=True)` → ŞURASI ÖNEMLİ.**
  `engine` tüm bağlantı havuzunu yönetir. `pool_pre_ping=True` → havuzdan bir bağlantı
  almadan önce "ping" atar; bağlantı kopmuşsa (ör. DB yeniden başladı) otomatik tazeler.
  Bu olmadan "bağlantı kapandı" hataları alırsınız.
- `SessionLocal = sessionmaker(...)` → bu bir **session fabrikası**. Her çağrıldığında yeni
  bir DB oturumu üretir. `autocommit=False` → değişiklikler `db.commit()` denene kadar kalıcı
  olmaz (işlem güvenliği).

### `get_db` — FastAPI dependency kalıbı

```python
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

**Bu method ne yapıyor?** FastAPI'nin "dependency injection" mekanizması için tasarlanmış.
- `db = SessionLocal()` → yeni oturum açar.
- `yield db` → oturumu endpoint fonksiyonuna **verir** (return değil yield, çünkü işten sonra
  devam etmesi gerekiyor).
- `finally: db.close()` → endpoint işini bitirince (başarılı ya da hatalı, fark etmez)
  oturum **garantili** kapanır. Bağlantı sızıntısını önler.

Kullanımı: endpoint'te `db: Session = Depends(get_db)` yazınca FastAPI her istek için
otomatik olarak bu fonksiyonu çalıştırır, oturumu enjekte eder, istek bitince kapatır.

---

## 1.3 Veri Şemaları — `schemas.py`

Pydantic modelleri, API'nin **giriş ve çıkış sözleşmesidir**. Gelen JSON otomatik doğrulanır,
giden veri otomatik biçimlenir.

### Enum'lar — sabit değer kümeleri

```python
class FillLevelEnum(str, Enum):
    EMPTY = "EMPTY"
    FULL = "FULL"
    CRITICAL_FULL = "CRITICAL_FULL"
    SENSOR_ERROR = "SENSOR_ERROR"


class AnomalyType(str, Enum):
    OVERFLOW_RISK = "OVERFLOW_RISK"
    UNAUTHORIZED_EMPTY = "UNAUTHORIZED_EMPTY"
    BIN_OFFLINE = "BIN_OFFLINE"
    FILL_ANOMALY = "FILL_ANOMALY"
    SENSOR_FIXED_VALUE_ERROR = "SENSOR_FIXED_VALUE_ERROR"
    SENSOR_NOT_FOUND_ERROR = "SENSOR_NOT_FOUND_ERROR"
```

**`class FillLevelEnum(str, Enum)` → ŞURASI ÖNEMLİ.** `str, Enum`'dan türetilmesi çift fayda sağlar:
1. **Tip güvenliği**: kodda `FillLevelEnum.FULL` yazarsınız, yazım hatası imkansız.
2. **String davranışı**: JSON'a yazılırken otomatik `"FULL"` olur, ayrı dönüşüm gerekmez.

**Kritik kural:** Bu enum'daki değerler (`EMPTY`, `FULL`, `CRITICAL_FULL`, `SENSOR_ERROR`)
ESP32 firmware'inin gönderdiği string'lerle **birebir aynı** olmak zorunda. Firmware
`"CRITICAL_FULL"` gönderir, backend burada onu tanır.

### Giriş modelleri — ESP32'nin gönderdiği gövdeler

```python
class StateChangeIn(BaseModel):
    enum_state: FillLevelEnum
    median_distance_cm: float | None = None
    event_timestamp: datetime | None = None


class HeartbeatIn(BaseModel):
    current_enum: FillLevelEnum | None = None
```

- `StateChangeIn` → ESP32 `POST /state-change` ile bunu gönderir. `enum_state` **zorunlu**,
  diğerleri opsiyonel (`| None = None`).
- `median_distance_cm: float | None` → opsiyonel çünkü sensör hatasında ölçüm gelmeyebilir.
- Pydantic, gelen JSON'da `enum_state` yoksa veya geçersiz bir değerse **otomatik 422 hatası**
  döner — manuel doğrulama yazmaya gerek kalmaz.

### Çıkış modelleri — frontend'e dönen veri

```python
class BinOut(BaseModel):
    bin_id: str
    lat: float
    lon: float
    status: str
    region: str
    last_emptied_at: datetime | None
    fill_level: FillLevelEnum | None = None
    is_active: bool | None = None
    last_seen_at: datetime | None = None
    last_enum_transition: str | None = None
    last_enum_change_at: datetime | None = None
    last_event_type: str | None = None
    last_event_at: datetime | None = None
```

Çıkış alanlarının çoğu `| None` çünkü bir kova henüz IoT verisi göndermemiş olabilir
(o zaman `fill_level`, `last_seen_at` vs. boş gelir). `response_model=BinOut` ile işaretlenen
endpoint, DB'den gelen fazla alanları **otomatik kırpar**, sadece bu modeldeki alanları döndürür.

---

## 1.4 FastAPI Giriş Noktası — `main.py`

Uygulamanın çatısı: lifespan kancası, CORS, ve endpoint tanımları.

### Lifespan — açılış/kapanış kancası

```python
@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Uygulama başlarken bin'leri engine'e yükle
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT bin_id, latitude AS lat, longitude AS lon,
                   region, fill_label, distance_label
            FROM bins
            ORDER BY bin_id
        """)).mappings().all()
        engine.load_bins([dict(r) for r in rows])
    except Exception as exc:
        print(f"[engine] Bin yüklenemedi: {exc}")
    finally:
        db.close()
    yield
    # Uygulama kapanırken simülasyonu durdur
    await engine.stop()
```

**Bu fonksiyon ne yapıyor?** FastAPI'nin yaşam döngüsü kancası. `yield`'in **öncesi** uygulama
ayağa kalkarken, **sonrası** kapanırken çalışır.

- `@asynccontextmanager` → fonksiyonu bir "async context manager" yapar; FastAPI bunu startup/shutdown
  için kullanır.
- **Açılış (yield öncesi):** DB'den tüm kovaları çeker (`bin_id`, konum, region ve simülasyon
  için gereken `fill_label`, `distance_label`) ve **simülasyon motoruna yükler**
  (`engine.load_bins`). Yani uygulama açılır açılmaz simülasyon kovaları hafızada hazır olur.
- `.mappings().all()` → her satırı sözlük benzeri (kolon adıyla erişilebilir) yapar.
- `try/except` → DB yoksa bile uygulama **çökmez**, sadece uyarı basar. Demo dayanıklılığı.
- **Kapanış (yield sonrası):** `await engine.stop()` → arka planda dönen simülasyon
  asyncio görevini temiz şekilde durdurur.

### Uygulama ve CORS

```python
app = FastAPI(title="EcoHaul API", lifespan=lifespan)
app.include_router(simulation.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- `app.include_router(simulation.router)` → simülasyon endpoint'lerini (`/api/simulation/...`)
  ana uygulamaya ekler. Bunlar `routers/simulation.py`'de tanımlı (Bölüm 4'te).
- **`CORSMiddleware ... allow_origins=["*"]` → ŞURASI ÖNEMLİ.** Tarayıcı güvenlik kuralı
  gereği, frontend (`localhost:5173`) farklı porttaki backend'e (`localhost:8000`) istek
  atamaz — CORS bunu açar. `["*"]` tüm origin'lere izin verir (geliştirme kolaylığı; üretimde
  daraltılmalı).

### Endpoint'ler — ince controller deseni

```python
@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/bins", response_model=list[BinOut])
def get_bins(db: Session = Depends(get_db)) -> list[dict]:
    return fetch_bins(db)


@app.get("/api/bins/summary", response_model=BinsSummaryOut)
def get_bins_summary(db: Session = Depends(get_db)) -> dict:
    return fetch_summary(db)


@app.get("/api/anomalies", response_model=list[AnomalyEventOut])
def get_anomalies(limit: int = 50, db: Session = Depends(get_db)) -> list[AnomalyEventOut]:
    return fetch_recent_anomalies(db, limit=limit)
```

**Önemli tasarım deseni:** Bu endpoint fonksiyonları **çok ince**. İş mantığını hiç içermezler,
sadece `services/` katmanındaki fonksiyonu çağırırlar (`fetch_bins`, `fetch_summary`, ...).

- `@app.get("/api/bins", response_model=list[BinOut])` → GET endpoint'i; dönen liste
  `BinOut` modeline göre filtrelenip doğrulanır.
- `db: Session = Depends(get_db)` → her istekte `get_db` çalışır, taze oturum enjekte edilir.
- `/health` → en basit endpoint; "backend ayakta mı?" kontrolü için.

Bu ayrım (ince endpoint + kalın servis) test ve bakımı kolaylaştırır: iş mantığını
endpoint'ten bağımsız test edebilirsiniz.

### POST endpoint'leri — ESP32'nin vurduğu yer

```python
@app.post("/api/devices/{bin_id}/state-change")
def post_state_change(
    bin_id: str,
    payload: StateChangeIn,
    db: Session = Depends(get_db),
) -> dict:
    try:
        log_state_change(db, bin_id, payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok"}


@app.post("/api/devices/{bin_id}/heartbeat")
def post_heartbeat(
    bin_id: str,
    payload: HeartbeatIn,
    db: Session = Depends(get_db),
) -> dict:
    try:
        log_heartbeat(db, bin_id, payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok"}
```

- `{bin_id}` → URL'deki **path parametresi**. ESP32 `/api/devices/WMS1872/state-change`
  vurduğunda `bin_id = "WMS1872"` olur.
- `payload: StateChangeIn` → gövdedeki JSON otomatik bu modele dönüşür ve doğrulanır.
- `try/except → HTTPException(500)` → iş mantığında hata olursa istemciye düzgün bir 500
  hatası döner, sunucu çökmez. `from exc` orijinal hatayı zincire ekler (debug için).

---

## 1.5 Bin Servisi — `bins_service.py`

İş mantığının çoğu burada. En kritik fonksiyon `log_state_change` — ESP32 ölçümünü
işleyen ana yer.

### CSV fallback — DB olmadan da çalışma

```python
ROOT_DIR = Path(__file__).resolve().parents[3]
FALLBACK_CSV = ROOT_DIR / "backend" / "data" / "bins_wgs84.csv"


def _load_bins_from_csv() -> list[dict]:
    if not FALLBACK_CSV.exists():
        return []

    bins: list[dict] = []
    with FALLBACK_CSV.open("r", encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            bins.append(
                {
                    "bin_id": row["bin_id"],
                    "lat": float(row["latitude"]),
                    "lon": float(row["longitude"]),
                    "status": row.get("status", "OFFLINE") or "OFFLINE",
                    "region": row.get("region", "Unknown") or "Unknown",
                    "last_emptied_at": None,
                }
            )
    return bins
```

**Bu method ne işe yarıyor?** Veritabanına erişilemezse, kovaları doğrudan CSV dosyasından
okur. Böylece backend, DB kurulu olmasa bile harita gösterebilir.
- `Path(__file__).resolve().parents[3]` → bu dosyadan 3 seviye yukarı çıkarak proje kökünü
  bulur (`services/` → `app/` → `backend/` → kök).
- `row.get("status", "OFFLINE") or "OFFLINE"` → status yoksa **veya boş string** ise `"OFFLINE"`.
  (`or` kısmı boş string'i de yakalar — `.get` sadece eksik anahtarı yakalar.)

### `fetch_bins` — DB önce, hata olursa CSV

```python 
def fetch_bins(db: Session) -> list[dict]:
    query = text("""
        SELECT bin_id, latitude AS lat, longitude AS lon, status, region,
               last_emptied_at, fill_level, is_active, last_seen_at,
               last_enum_transition, last_enum_change_at
        FROM bins ORDER BY bin_id
    """)
    try:
        rows = db.execute(query).mappings().all()
        return [dict(row) for row in rows]
    except SQLAlchemyError:
        return _load_bins_from_csv()
```

**`except SQLAlchemyError: return _load_bins_from_csv()` → ŞURASI ÖNEMLİ.** Bu, sistemin
dayanıklılık (resilience) deseni: DB hatası olsa bile çökmez, CSV'ye düşer. Demo/sunum
ortamında "DB bağlanamadı" diye haritanın boş kalmasını engeller.

### `log_state_change` — EN KRİTİK FONKSİYON

ESP32'den gelen her ölçüm bu fonksiyondan geçer. Adım adım:

**Adım 1 — Ham ölçümü telemetry'ye yaz:**

```python
def log_state_change(db: Session, bin_id: str, payload: StateChangeIn) -> None:
    telemetry_query = text("""
        INSERT INTO telemetry (bin_id, enum_state, raw_distance_cm)
        VALUES (:bin_id, :enum_state, :raw_distance_cm)
    """)
    db.execute(
        telemetry_query,
        {
            "bin_id": bin_id,
            "enum_state": payload.enum_state.value,
            "raw_distance_cm": payload.median_distance_cm,
        },
    )
```

Her ölçüm önce `telemetry` tablosuna **geçmiş kaydı** olarak işlenir. `:bin_id` gibi
parametreler **SQL injection'a karşı güvenli** bağlama (binding) kullanır — string birleştirme
yapılmaz.

**Adım 2 — Önceki seviyeyi yakala (geçiş tespiti için):**

```python
    previous_level_query = text("""
        SELECT fill_level FROM bins WHERE bin_id = :bin_id
    """)
    previous_level_value = db.execute(
        previous_level_query, {"bin_id": bin_id}
    ).scalar_one_or_none()
```

Güncellemeden **önce** mevcut `fill_level` okunur. Bunu sonra "durum gerçekten değişti mi?"
kontrolünde kullanacağız. `scalar_one_or_none()` → tek değer döner, kova yoksa `None`.

**Adım 3 — Kovanın anlık durumunu güncelle (akıllı CASE):**

```python
    update_query = text("""
        UPDATE bins
        SET
            last_enum_transition = CASE
                WHEN fill_level IS NULL OR fill_level = :new_fill_level THEN last_enum_transition
                ELSE fill_level || '->' || :new_fill_level
            END,
            last_enum_change_at = CASE
                WHEN fill_level IS NULL OR fill_level = :new_fill_level THEN last_enum_change_at
                ELSE COALESCE(:event_timestamp, NOW())
            END,
            fill_level = :new_fill_level,
            is_active = TRUE,
            last_seen_at = COALESCE(:event_timestamp, NOW()),
            status = CASE
                WHEN :new_fill_level = 'CRITICAL_FULL' THEN 'CRITICAL_FULL'
                WHEN :new_fill_level = 'FULL' THEN 'FULL'
                WHEN :new_fill_level = 'EMPTY' THEN 'EMPTY'
                ELSE status
            END
        WHERE bin_id = :bin_id
    """)
    db.execute(update_query, {
        "bin_id": bin_id,
        "new_fill_level": payload.enum_state.value,
        "event_timestamp": payload.event_timestamp,
    })
```

**Bu SQL'in zekası — ŞURASI ÖNEMLİ:**
- `last_enum_transition` CASE bloğu: Eğer eski seviye **boş** ya da yeni seviyeyle **aynıysa**,
  eski geçiş özetini korur. Aksi halde `fill_level || '->' || :new_fill_level` ile
  `"EMPTY->FULL"` üretir (`||` PostgreSQL'de string birleştirme).
  → **Anlamı:** Sadece gerçek bir durum değişikliği olduğunda geçiş kaydedilir. "FULL→FULL"
  gibi gereksiz kayıt oluşmaz.
- `COALESCE(:event_timestamp, NOW())` → ESP32 zaman damgası gönderdiyse onu, göndermediyse
  sunucu saatini kullanır.
- `status` CASE → enum'u harita statüsüne çevirir (kova marker rengini belirler).

**Adım 4 — Anomali kontrollerini çalıştır:**

```python
    try:
        new_level_enum = payload.enum_state
        check_overflow_risk(db, bin_id, new_level_enum, payload.event_timestamp, previous_level_value)
        check_sensor_error_flag(db, bin_id, new_level_enum, payload.event_timestamp)
        check_sensor_fixed_value_error(db, bin_id)
        check_fill_anomaly(db, bin_id)
    except Exception:
        # Anomaly detection must not break state-change handling
        pass

    db.commit()
```

**`except Exception: pass` → ŞURASI ÖNEMLİ ve bilinçli.** 4 anomali kuralı çalıştırılır
(Bölüm 1.6). Bir tanesi hata verirse **ana akış bozulmaz** — hata yutulur. Mantık: anomali
tespiti ikincil bir özellik; bir hata yüzünden ESP32'nin verisini kaydetmeyi başaramamak
kabul edilemez. `db.commit()` → adım 1-4'teki tüm değişiklikler tek seferde kalıcı olur.

**Adım 5 — Canlı simülasyona enjekte et:**

```python
    try:
        from ..simulation_engine import engine
        engine.inject_sensor_reading(
            bin_id=bin_id,
            enum_state=payload.enum_state.value,
            median_distance_cm=payload.median_distance_cm,
        )
    except Exception:
        pass
```

**`from ..simulation_engine import engine` → fonksiyon içinde import edilmesine dikkat.**
Bu **lazy import** (geç içe aktarma) — döngüsel bağımlılığı kırmak için. `simulation_engine`
de dolaylı olarak servisleri kullanır; modül seviyesinde import edersek "circular import"
hatası alınır. Gerçek sensör verisi hem DB'ye yazılır hem canlı simülasyon dünyasına işlenir
(Bölüm 4'te `inject_sensor_reading`).

### `log_heartbeat` — daha hafif güncelleme

```python
def log_heartbeat(db: Session, bin_id: str, payload: HeartbeatIn) -> None:
    update_query = text("""
        UPDATE bins
        SET is_active = TRUE,
            last_seen_at = NOW(),
            fill_level = COALESCE(:fill_level, fill_level)
        WHERE bin_id = :bin_id
    """)
    db.execute(update_query, {
        "bin_id": bin_id,
        "fill_level": payload.current_enum.value if payload.current_enum else None,
    })
    db.commit()
```

Heartbeat, ESP32'nin "ben hayattayım" sinyali (8 saatte bir). State-change'den farkı:
- **Geçiş özetine dokunmaz** (`last_enum_transition` güncellenmez) — çünkü durum değişmedi,
  sadece cihaz canlı olduğunu bildiriyor.
- `COALESCE(:fill_level, fill_level)` → heartbeat bir enum taşıyorsa günceller, taşımıyorsa
  mevcut değeri korur.

---

## 1.6 Anomali Servisi — `anomaly_service.py`

4 kural-tabanlı anomali tespitçisi + ortak yazıcı.

### Ortak yazıcı — `log_anomaly_event`

```python
def log_anomaly_event(db, bin_id, event_type, details=None):
    details_str = json.dumps(details) if details is not None else None

    insert_query = text("""
        INSERT INTO event_log (bin_id, event_type, details)
        VALUES (:bin_id, :event_type, :details)
    """)
    db.execute(insert_query, {"bin_id": bin_id, "event_type": event_type.value, "details": details_str})

    update_summary_query = text("""
        UPDATE bins
        SET last_event_type = :event_type, last_event_at = COALESCE(:event_timestamp, NOW())
        WHERE bin_id = :bin_id
    """)
    db.execute(update_summary_query, {
        "bin_id": bin_id,
        "event_type": event_type.value,
        "event_timestamp": (details or {}).get("event_timestamp") if details else None,
    })
```

Her anomali **iki yere** yazılır: `event_log` tablosuna (tam kayıt) + `bins` tablosunun özet
alanlarına (`last_event_type`). Böylece hem geçmiş tutulur hem "bu kovanın son anomalisi ne?"
hızlı sorgulanır. `json.dumps(details)` → ek bilgileri JSON metni olarak saklar.

### Kural 1 — Taşma Riski

```python
def check_overflow_risk(db, bin_id, new_level, event_timestamp, previous_level):
    if new_level != FillLevelEnum.CRITICAL_FULL:
        return

    if previous_level == FillLevelEnum.CRITICAL_FULL.value:
        return

    details: dict = {}
    if event_timestamp is not None:
        details["event_timestamp"] = event_timestamp.isoformat()

    log_anomaly_event(db, bin_id, AnomalyType.OVERFLOW_RISK, details or None)
```

**Mantık:** Kova `CRITICAL_FULL`'a **geçtiyse** taşma riski var.
- İlk `if` → yeni durum kritik değilse hiç ilgilenme.
- **İkinci `if` → ŞURASI ÖNEMLİ.** Eğer **zaten** kritikti, tekrar loglama. Yoksa kova
  kritikte kaldıkça her heartbeat'te yeni anomali üretilir = log spam'i. Sadece **geçiş anında**
  bir kez kaydeder.

### Kural 2 — Cihaz sensör hatası bildirdi

```python
def check_sensor_error_flag(db, bin_id, new_level, event_timestamp):
    if new_level != FillLevelEnum.SENSOR_ERROR:
        return
    details: dict = {}
    if event_timestamp is not None:
        details["event_timestamp"] = event_timestamp.isoformat()
    log_anomaly_event(db, bin_id, AnomalyType.SENSOR_NOT_FOUND_ERROR, details or None)
```

ESP32 doğrudan `SENSOR_ERROR` gönderdiyse (ölçüm alamadı), bunu `SENSOR_NOT_FOUND_ERROR`
anomalisi olarak loglar. Firmware kaynaklı donanım hataları her zaman görünür olsun diye.

### Kural 3 — Takılı sensör değeri (geçmişe bakan tespit)

```python
def check_sensor_fixed_value_error(db, bin_id, window_size=3, tolerance_cm=0.2):
    query = text("""
        SELECT raw_distance_cm FROM telemetry
        WHERE bin_id = :bin_id AND raw_distance_cm IS NOT NULL
        ORDER BY created_at DESC LIMIT :limit
    """)
    rows = db.execute(query, {"bin_id": bin_id, "limit": window_size}).mappings().all()
    if len(rows) < window_size:
        return  # yeterli geçmiş yok

    distances = [row["raw_distance_cm"] for row in rows if row["raw_distance_cm"] is not None]
    if len(distances) < window_size:
        return

    min_val = min(distances)
    max_val = max(distances)

    if max_val - min_val <= tolerance_cm:
        details = {"window_size": window_size, "min_distance_cm": min_val, "max_distance_cm": max_val}
        log_anomaly_event(db, bin_id, AnomalyType.SENSOR_FIXED_VALUE_ERROR, details)
```

**Bu method ne yapıyor?** Son 3 ham mesafe ölçümünü çeker. Hepsi **0.2 cm toleransı içinde**
aynıysa (`max - min <= 0.2`), sensör donmuş/takılmış demektir — gerçek dünyada çöp seviyesi
asla 3 ölçüm boyunca milimetrik aynı kalmaz. Bu, **geçmişe bakarak** çalışan tek anomali
(diğerleri anlık veriyi inceler). `idx_telemetry_bin_id_created_at` index'i bu sorguyu hızlandırır.

### Kural 4 — Şüpheli dolum paterni

```python
def check_fill_anomaly(db, bin_id, time_window_minutes=15):
    query = text("""
        SELECT enum_state, created_at FROM telemetry
        WHERE bin_id = :bin_id ORDER BY created_at DESC LIMIT 3
    """)
    rows = db.execute(query, {"bin_id": bin_id}).mappings().all()
    if len(rows) < 3:
        return

    newest, mid, oldest = rows[0], rows[1], rows[2]

    if not (
        newest["enum_state"] == FillLevelEnum.EMPTY.value
        and mid["enum_state"] == FillLevelEnum.CRITICAL_FULL.value
        and oldest["enum_state"] == FillLevelEnum.EMPTY.value
    ):
        return

    try:
        start_time = oldest["created_at"]
        end_time = newest["created_at"]
    except Exception:
        return

    if end_time - start_time <= timedelta(minutes=time_window_minutes):
        details = {
            "start_timestamp": start_time.isoformat() if isinstance(start_time, datetime) else str(start_time),
            "end_timestamp": end_time.isoformat() if isinstance(end_time, datetime) else str(end_time),
        }
        log_anomaly_event(db, bin_id, AnomalyType.FILL_ANOMALY, details)
```

**Mantık — ŞURASI ÖNEMLİ:** Son 3 ölçüm `EMPTY → CRITICAL_FULL → EMPTY` paterni oluşturuyorsa
**ve** bu 15 dakika içinde olduysa, fiziksel olarak imkansız hızda dolup boşalmış → muhtemelen
hatalı sensör ya da manipülasyon. `rows` en yeniden eskiye sıralı (`DESC`), bu yüzden
`newest/mid/oldest` indexleri 0/1/2.

### `fetch_recent_anomalies` — frontend için son anomaliler

```python
def fetch_recent_anomalies(db, limit=50):
    query = text("""
        SELECT bin_id, event_type, details, created_at FROM event_log
        ORDER BY created_at DESC LIMIT :limit
    """)
    rows = db.execute(query, {"limit": limit}).mappings().all()

    events: list[AnomalyEventOut] = []
    for row in rows:
        events.append(AnomalyEventOut(
            bin_id=row["bin_id"],
            event_type=AnomalyType(row["event_type"]),
            details=row["details"],
            created_at=row["created_at"],
        ))
    return events
```

`event_log`'tan en yeni `limit` (varsayılan 50) anomaliyi çeker, her satırı `AnomalyEventOut`
Pydantic modeline çevirir. `AnomalyType(row["event_type"])` → metin string'i enum'a geri
dönüştürür (doğrulama da yapar — bilinmeyen tip hatası verir).

---

**Sonraki bölüm:** [KOD_DETAY_2 — DPET Algoritması](KOD_DETAY_2_DPET_ALGORITMA.md)
