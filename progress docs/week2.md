
## Week 2: IoT Sensör Entegrasyonu ve Uçtan Uca Çalışan Sistem

### 1. IoT Sensör (ESP32 + HC-SR04) Tarafı

- ESP32 için tek dosyalı bir firmware yazıldı (Arduino/ESP32 core):
	- HC-SR04 ultrasonik sensörden 10 ölçüm alıp median mesafeyi hesaplıyor.
	- Kovanın yüksekliğine göre doluluk yüzdesi hesaplanıyor.
	- Doluluk yüzdesine göre dört durumdan biri atanıyor:
		- `EMPTY`
		- `FULL`
		- `CRITICAL_FULL`
		- `SENSOR_ERROR` (ölçüm hatalarında)
	- RTC (RTC_DATA_ATTR) ile iki bilgi uykular arasında korunuyor:
		- Son enum değeri (`rtc_lastLevelInt`)
		- Uyanma sayacı (`rtc_wakeCounter`)
	- Çalışma döngüsü:
		- Her uyanışta ölçüm + enum hesaplanır.
		- Enum değişmişse **state-change** POST atılır.
		- Enum değişmese bile en geç 8 uyanmada bir **heartbeat** POST atılır.
		- İş bittikten sonra ESP32, `esp_deep_sleep` ile ~1 saatlik derin uykuya geçer.
- WiFi ve HTTP entegrasyonu:
	- SSID/şifre üzerinden WiFi bağlantısı kuruluyor.
	- `BACKEND_BASE_URL` ile FastAPI backend’ine HTTP POST istekleri atılıyor.
	- Başarılı istekler için Serial Monitor’da cevap kodu ve body loglanıyor.

### 2. Backend Veritabanı Şeması (PostgreSQL + PostGIS)

- Yeni bir PostgreSQL 16.13 sunucusu Windows üzerinde kuruldu.
- `ecohaul` adında bir veritabanı oluşturuldu.
- PostGIS uzantısı StackBuilder ile kuruldu ve veritabanında aktif edildi.
- [backend/database/init.sql](backend/database/init.sql) ile şema tanımlandı:
	- `bins` tablosu:
		- Mevcut alanlar: `id`, `bin_id`, `latitude`, `longitude`, `status`, `region`, `last_emptied_at`, `geom` (GEOGRAPHY(Point, 4326)).
		- IoT alanları eklendi:
			- `fill_level` (TEXT)
			- `is_active` (BOOLEAN, varsayılan TRUE)
			- `last_seen_at` (TIMESTAMP)
			- `last_enum_transition` (TEXT, örn. `EMPTY->FULL`)
			- `last_enum_change_at` (TIMESTAMP)
	- `telemetry` tablosu:
		- `id`, `bin_id`, `enum_state`, `raw_distance_cm`, `created_at` alanları ile her ölçüm için ayrı kayıt tutuyor.
- [backend/scripts/load_bins_to_db.py](backend/scripts/load_bins_to_db.py):
	- `bins_wgs84.csv` dosyasından 3421 adet kayıt okunup `bins` tablosuna yükleniyor.
	- NaN olan `last_emptied_at` değerleri `NULL`’a çevrildi, böylece timestamp kolonuna doğru yazılıyor.
	- Yeni IoT alanları için varsayılanlar atanıyor (`fill_level=None`, `is_active=True` vb.).
	- `geom` alanı PostGIS fonksiyonları (`ST_MakePoint`, `ST_SetSRID`) ile dolduruluyor.

### 3. Backend Uygulaması (FastAPI)

- Veritabanı bağlantısı:
	- [backend/app/database.py](backend/app/database.py) içinde `DATABASE_URL` varsayılanı:
		- `postgresql+psycopg://postgres:sharku241@localhost:5432/ecohaul`
	- SQLAlchemy `engine` ve `SessionLocal` ile DB bağlantısı yönetiliyor.
- Şema (Pydantic modeller):
	- [backend/app/schemas.py](backend/app/schemas.py) içinde:
		- `FillLevelEnum` (`EMPTY`, `FULL`, `CRITICAL_FULL`).
		- `StateChangeIn`: IoT cihazından gelen state-change için gövde şeması (enum + median mesafe + timestamp).
		- `HeartbeatIn`: heartbeat için isteğe bağlı current enum alanı.
		- `BinOut`: Frontend’e dönen bin objesi; yeni IoT alanları da dahil.
- Servis katmanı:
	- [backend/app/services/bins_service.py](backend/app/services/bins_service.py):
		- `fetch_bins`: `bins` tablosundan tüm kovaları IoT alanlarıyla birlikte döner.
		- `fetch_summary`: toplam kova, offline kova ve bölgelere göre dağılımı hesaplar.
		- `log_state_change`:
			- `telemetry` tablosuna yeni bir satır ekler (`enum_state`, `raw_distance_cm`).
			- `bins` tablosunda ilgili `bin_id` için:
				- `fill_level`, `status`, `is_active`, `last_seen_at` güncellenir.
				- `last_enum_transition` ve `last_enum_change_at`, eski `fill_level` ile yeni enum’a göre güncellenir.
			- İşlemler sonunda `db.commit()` ile değişiklikler kalıcı hale getirilir.
		- `log_heartbeat`:
			- Sadece `is_active`, `last_seen_at` ve opsiyonel olarak `fill_level` güncellenir.
			- `last_enum_transition` alanına dokunulmaz.
			- Değişiklikler `db.commit()` ile kaydedilir.
- API endpoint’leri:
	- [backend/app/main.py](backend/app/main.py):
		- `GET /health`: Sağlık kontrolü.
		- `GET /api/bins`: Tüm kovaları `BinOut` şemasına göre döner.
		- `GET /api/bins/summary`: Özet istatistikleri döner.
		- `POST /api/devices/{bin_id}/state-change`:
			- ESP32’den gelen doluluk durumunu `log_state_change` ile işler.
		- `POST /api/devices/{bin_id}/heartbeat`:
			- Cihazın hala aktif olduğunu `log_heartbeat` ile kaydeder.

### 4. ESP32 → Backend → Veritabanı Entegrasyonu

- ESP32, ölçüm sonrası şu isteği başarıyla atıyor (örnek):
	- `POST http://192.168.1.133:8000/api/devices/WMS1873/state-change`
	- Body: `{"enum_state":"FULL","median_distance_cm":40.17}`
	- Backend yanıtı: `HTTP 200` ve `{"status":"ok"}`.
- Bu istek sonucunda veritabanında:
	- `telemetry` tablosuna yeni bir kayıt ekleniyor.
	- `bins` tablosundaki ilgili satırda:
		- `status` alanı `FULL` olarak güncelleniyor.
		- `fill_level` alanı `FULL` oluyor.
		- `is_active = TRUE`, `last_seen_at = NOW()` değerleri atanıyor.
		- Gerekirse `last_enum_transition` ve `last_enum_change_at` güncelleniyor.

### 5. Frontend (React + Vite + Leaflet) Güncellemeleri

- Harita bileşeni: [frontend/src/components/MapView.jsx](frontend/src/components/MapView.jsx)
	- Önceden tüm marker’lar gri tek bir ikonla gösteriliyordu.
	- Artık `bin.status` alanına göre farklı renklerde ikonlar kullanılıyor:
		- `OFFLINE` → gri (mevcut stil).
		- `EMPTY` → yeşil.
		- `FULL` → turuncu.
		- `CRITICAL_FULL` → kırmızı.
	- Bu ikonlar `L.divIcon` ve ilgili CSS sınıflarıyla tanımlandı.
- Stil dosyası: [frontend/src/App.css](frontend/src/App.css)
	- `.bin-marker-empty`, `.bin-marker-full`, `.bin-marker-critical` sınıfları eklendi.
	- Böylece IoT’den gelen doluluk durumları haritada renk kodlarıyla görülebiliyor.

### 6. Uçtan Uca Çalışan Senaryo

1. PostgreSQL ve PostGIS kurulu, `ecohaul` veritabanı içinde `bins` ve `telemetry` tabloları oluşturulmuş durumda.
2. `load_bins_to_db.py` script’i ile 3421 kova kaydı CSV’den veritabanına yüklendi.
3. FastAPI backend’i `uvicorn` ile `http://localhost:8000` adresinde çalışıyor.
4. Frontend harita arayüzü Vite ile `http://localhost:5173` veya `5174` portundan servis ediliyor.
5. ESP32 + HC-SR04 sensörü, belirlenen periyotlarda:
	 - Ölçüm yapıyor,
	 - Enum durumunu hesaplıyor,
	 - Backend’e state-change/heartbeat POST istekleri atıyor,
	 - DB’de ilgili `bin_id` satırı güncelleniyor.
6. Kullanıcı, harita arayüzünde ilgili kovayı seçerek hem son `status`/`fill_level` durumunu hem de backend API üzerinden son güncellemeleri görebiliyor.

Bu haftada hedeflenen IoT sensör → backend → veritabanı → frontend zinciri uçtan uca kurulmuş ve gerçek donanım üzerinden doğrulanmış oldu.

