# EcoHaul AI — ESP32 IoT Katmanı Teknik Dokümantasyonu

**Konu:** Ultrasonik Sensör + ESP32 ile Gerçek Konteyner Doluluk Tespiti  
**Ders:** CSE-492 Bitirme Projesi  
**Tarih:** Mart 2026  
**Bağlı Modül:** `backend/api/anomaly_engine.py` · `backend/api/heartbeat_manager.py`

---

## İçindekiler

1. [Genel Bakış — ESP32'nin Pipeline'daki Yeri](#1-genel-bakış--esp32nin-pipelinedaki-yeri)
2. [Donanım Bileşenleri](#2-donanım-bileşenleri)
3. [Devre Şeması](#3-devre-şeması)
4. [Mesafe → Doluluk Dönüşümü](#4-mesafe--doluluk-dönüşümü)
5. [Firmware Mimarisi](#5-firmware-mimarisi)
6. [Heartbeat Zamanlama — 3-Loop Miss Counter ile Senkronizasyon](#6-heartbeat-zamanlama--3-loop-miss-counter-ile-senkronizasyon)
7. [API Entegrasyonu — HTTP Payload'ları](#7-api-entegrasyonu--http-payloadları)
8. [Hata Yönetimi ve Yeniden Bağlantı](#8-hata-yönetimi-ve-yeniden-bağlantı)
9. [Güç Tüketimi ve Deep Sleep Stratejisi](#9-güç-tüketimi-ve-deep-sleep-stratejisi)
10. [Firmware Kaynak Kodu (Tam)](#10-firmware-kaynak-kodu-tam)
11. [Simülatör ↔ Gerçek Donanım Karşılaştırması](#11-simülatör--gerçek-donanım-karşılaştırması)
12. [Kurulum ve Flash Adımları](#12-kurulum-ve-flash-adımları)
13. [Test ve Doğrulama](#13-test-ve-doğrulama)

---

## 1. Genel Bakış — ESP32'nin Pipeline'daki Yeri

EcoHaul veri akışında ESP32, Katman 0 (Ham Veri) ile Katman 1 (İşleme) arasında köprü kurar. Simülatörün (`iot_simulator.py`) gerçek donanımla değiştirildiği nokta burasıdır.

```
┌──────────────────────────────────────────────────────────────────┐
│                    EcoHaul Veri Akışı                            │
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                ESP32 + JSN-SR04T                          │  │
│  │                                                           │  │
│  │  [Ultrasonik Sensör]                                      │  │
│  │    Konteyner tabanına ultrasonik darbe gönder             │  │
│  │    Yankı süresi ölç → mesafe hesapla (cm)                 │  │
│  │    Mesafe → Doluluk % → LOW / MEDIUM / HIGH               │  │
│  │                                                           │  │
│  │  [WiFi Stack]                                             │  │
│  │    POST /update-fill  {"bin_id": "WMS4505",               │  │
│  │                        "fill_level": "HIGH"}              │  │
│  │    POST /heartbeat    {"bin_id": "WMS4505"}               │  │
│  └───────────────────────────────────────────────────────────┘  │
│                           │                                      │
│                           ▼                                      │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              FastAPI Backend                              │  │
│  │   anomaly_engine.py ── heartbeat_manager.py              │  │
│  │         │                                                │  │
│  │         ▼                                                │  │
│  │   PostgreSQL + PostGIS                                   │  │
│  │   telemetry · event_log · bins                           │  │
│  └───────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

**Simülatör ile Gerçek Donanım Arasındaki Fark:**

`iot_simulator.py` yazılımsal bir olasılık modeli kullanır —
```python
if random.random() < fill_probability[hour]:
    # doluluk artır (LOW→MEDIUM veya MEDIUM→HIGH)
```

ESP32 fiziksel bir ölçüm yapar —
```
distance_cm = measureUltrasonic()  # HC-SR04 / JSN-SR04T
fill_pct    = (BIN_HEIGHT - distance_cm) / BIN_HEIGHT * 100
fill_level  = classify(fill_pct)   # LOW / MEDIUM / HIGH
```

API kontratı (`POST /update-fill`, `POST /heartbeat`) her iki kaynakta da **aynıdır**. Backend bir değişikliğe ihtiyaç duymaz.

---

## 2. Donanım Bileşenleri

### 2.1 Bileşen Seçim Matrisi

| Bileşen | Seçilen Model | Alternatif | Seçim Gerekçesi |
|---|---|---|---|
| **Mikrodenetleyici** | ESP32-WROOM-32D | ESP8266, Arduino+SIM | WiFi + Bluetooth, 4MB flash, 520KB SRAM, çift çekirdek |
| **Ultrasonik Sensör** | JSN-SR04T-2.0 | HC-SR04, VL53L0X | Su geçirmez gövde — açık hava çöp kutusu için kritik |
| **Güç** | 18650 Li-Ion + TP4056 | Direkt 5V USB | Deep sleep ile uzun pil ömrü |
| **Levye Devre** | PCB/Breadboard | — | TRIG/ECHO 5V←→3.3V level shift |

### 2.2 ESP32-WROOM-32D Teknik Özellikler

| Parametre | Değer |
|---|---|
| İşlemci | Xtensa LX6, çift çekirdek, 240 MHz |
| Flash | 4 MB |
| SRAM | 520 KB |
| WiFi | 802.11 b/g/n, 2.4 GHz |
| GPIO | 38 pin (3.3V tolerans) |
| ADC | 12-bit, 18 kanal |
| Deep Sleep Akımı | ~10 µA |
| Aktif WiFi Akımı | ~160–260 mA |
| Çalışma Voltajı | 3.0–3.6V |

### 2.3 JSN-SR04T-2.0 Teknik Özellikler

| Parametre | Değer | Açıklama |
|---|---|---|
| Ölçüm Aralığı | 20 cm – 600 cm | Güvenilir aralık |
| Çözünürlük | 1 mm | |
| Frekans | 40 kHz | Ultrasonik |
| Giriş Voltajı | 5V DC | ESP32 GPIO 3.3V → level shift gerekir |
| TRIG Pulse | ≥ 10 µs | Ölçüm tetikleme |
| Yankı Süresi | distance_cm / 0.0172 µs | Formül aşağıda |
| Gövde | IP65 su geçirmez | Açık hava için uygun |

> **Neden HC-SR04 değil?** HC-SR04 tahtası tamamen açık — nem, yağmur ve konteyner içi buharlanmada hızla arıza yapar. JSN-SR04T aynı çip setini su geçirmez problu gövdede sunar; proje Dublin'in yağışlı iklimine yönelik olduğundan bu tercih zorunludur.

---

## 3. Devre Şeması

### 3.1 Pin Bağlantıları

```
ESP32-WROOM-32D              JSN-SR04T-2.0
─────────────────            ──────────────
GPIO 5  (TRIG_PIN) ──────────► TRIG
GPIO 18 (ECHO_PIN) ◄──────────  ECHO  *
GND                ──────────── GND
3.3V               ──── [LD1117] ─── VCC (+5V)

* ECHO hattı 5V çıkış verir — 3.3V ESP32 girişi için
  gerilim bölücü zorunludur:
  
  ECHO (5V) ──[R1: 1kΩ]──┬── GPIO18 (ESP32)
                          │
                        [R2: 2kΩ]
                          │
                         GND
  
  Çıkış voltajı: 5V × (2000/(1000+2000)) = 3.33V ✓
```

### 3.2 Güç Katmanı

```
18650 Li-Ion (3.7V, 2200 mAh)
         │
    [TP4056 módülü]  ◄── USB Şarj
         │ (4.2V – 2.7V aralığı)
    [MT3608 Booster] → 5V (JSN-SR04T için)
         │
    [AMS1117-3.3]   → 3.3V (ESP32 VIN)
         │
    [ESP32 VIN]
```

**Tahmini Pil Ömrü Hesabı:**

- Aktif ölçüm + WiFi TX: 220 mA × 3 sn = 0.18 mAh / döngü
- Deep sleep arası: 30 dakika (1800 sn), 10 µA tüketim = 0.005 mAh
- Toplam / saat (2 döngü): `2 × 0.18 + 0.005 ≈ 0.365 mAh/saat`
- 2200 mAh pil ömrü: `2200 / 0.365 ≈ 6.027 saat → ~250 gün`

> Deep sleep aralığı 30 dakikada bir heartbeat göndermek üzerine kalibre edilmiştir. Detay §6'da.

---

## 4. Mesafe → Doluluk Dönüşümü

### 4.1 Ultrasonik Mesafe Formülü

Sesin havadaki hızı ~343 m/s (20°C). JSN-SR04T, TRIG'den sonra ECHO pinini `HIGH` tutar — bu süre sesin gidip gelmesidir:

$$distance_{cm} = \frac{t_{echo}[\mu s] \times 0.0343}{2}$$

`t_echo / 2`: ses hem gidip hem geliyor, yarısı tek yön mesafesidir.

```c
// ESP32 C++ (Arduino framework)
long duration = pulseIn(ECHO_PIN, HIGH);          // µs
float distance = duration * 0.0343 / 2.0;         // cm
```

### 4.2 Doluluk Yüzdesi Hesabı

Sensör konteynerin kapağına monte edilir, aşağıya bakarak taban mesafesini ölçer:

```
      ┌──────────────────────┐  ← Kapak (sensör burada)
      │    [JSN-SR04T]       │
      │         │            │
      │    distance_cm       │  ← Ölçülen mesafe
      │         │            │
      │         ▼            │
      │   ┌──────────┐       │
      │   │ ATIK     │       │  ← Atık seviyesi
      │   │          │       │
      │   └──────────┘       │
      │                      │  BIN_HEIGHT_CM = 100 cm (örnek)
      └──────────────────────┘  ← Taban
```

$$fill\_pct = \frac{BIN\_HEIGHT - distance_{cm}}{BIN\_HEIGHT} \times 100$$

### 4.3 Eşik Sınıflandırması (fill_level enum)

| fill_pct Aralığı | fill_level | Backend Anomali Sonucu |
|---|---|---|
| 0% – 33% | `"LOW"` | Normal |
| 34% – 66% | `"MEDIUM"` | Normal (`LOW→MEDIUM` geçişi) |
| 67% – 100% | `"HIGH"` | `OVERFLOW_RISK` event (eğer `MEDIUM→HIGH`) |
| >100% (sensör arızası) | Ölçüm reddedilir | HTTP isteği atılmaz |

```c
String classifyFillLevel(float fill_pct) {
    if (fill_pct < 0 || fill_pct > 110) return "ERROR";  
    if (fill_pct <= 33.0) return "LOW";
    if (fill_pct <= 66.0) return "MEDIUM";
    return "HIGH";
}
```

### 4.4 Gürültü Filtreleme — Medyan Filtresi

Tek ölçüm güvenilir değildir (titreşim, hava akımı). 5 ölçümün medyanı alınır:

```c
float measurements[5];
for (int i = 0; i < 5; i++) {
    measurements[i] = measureDistance();
    delay(60);  // sensör toparlanma süresi
}
// Sıralayıp ortadakini al
sort(measurements, measurements + 5);
float stable_distance = measurements[2];  // medyan
```

**Neden medyan, ortalama değil?** Bir aralık içindeki tek aykırı ölçüm (örn. kuş konuştu, çöp fırladı) ortalamayı bozar ama medyanı etkilemez.

---

## 5. Firmware Mimarisi

### 5.1 Ana Döngü Akışı

```
┌─────────────────────────────────────────────────────────────────┐
│                    ESP32 Firmware Akışı                         │
│                                                                 │
│  [BOOT / WAKE]                                                  │
│       │                                                         │
│       ▼                                                         │
│  WiFi bağlantısı kur (maksimum 10 sn, 3 deneme)                │
│       │                  │                                      │
│       │ Başarısız        │ Başarılı                            │
│       ▼                  ▼                                      │
│  Hata LED yak     [ULTRASONİK ÖLÇÜM]                           │
│  Deep sleep       5 ölçüm → medyan → fill_pct                  │
│  (retry sonra)         │                                        │
│                        ▼                                        │
│                  fill_level sınıflandır                         │
│                  (LOW / MEDIUM / HIGH)                          │
│                        │                                        │
│             ┌──────────┴──────────┐                            │
│             │                     │                             │
│      fill_level değişti?    Heartbeat zamanı geldi?            │
│             │ Evet               │ Evet (her 30 dk)            │
│             ▼                    ▼                              │
│      POST /update-fill    POST /heartbeat                       │
│      {"bin_id":...,       {"bin_id":...}                        │
│       "fill_level":...}        │                                │
│             │                  │                                │
│             └──────────┬───────┘                                │
│                        │                                        │
│                        ▼                                        │
│               RTC memory'ye son_fill_level yaz                  │
│               boot_count++                                      │
│                        │                                        │
│                        ▼                                        │
│               [DEEP SLEEP — 30 dakika]                          │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 RTC Memory — Deep Sleep Arası Veri Kalıcılığı

Deep sleep sırasında SRAM silinir. Ancak ESP32'nin 8KB **RTC slow memory**'si güçte kalır. Son `fill_level` buraya yazılır — boot sonrası değişim tespiti için:

```c
RTC_DATA_ATTR char   last_fill_level[10] = "LOW";   // SRAM silinse de kalır
RTC_DATA_ATTR int    boot_count          = 0;
RTC_DATA_ATTR long   last_heartbeat_ms   = 0;
```

Örnek: Konteynere son gidişte `MEDIUM` ölçtük. 30 dakika deep sleep. Uyandık, `HIGH` ölçtük. `last_fill_level ("MEDIUM") != current ("HIGH")` → `POST /update-fill` et.

**Eğer yazmadan uyusaydık:** Her boot'ta "LOW" ile kıyaslayacaktı → `LOW→HIGH` geçişi → `FILL_SKIP_ANOMALY` event hatalı tetiklenecekti. Bu yan etkiyi önler.

---

## 6. Heartbeat Zamanlama — 3-Loop Miss Counter ile Senkronizasyon

Bu bölüm firmware'deki heartbeat aralığını, backend'in heartbeat_manager.py ile nasıl senkronize tutacağını açıklar.

### 6.1 Backend'in Beklentisi

`heartbeat_manager.py` in-memory miss sayacı:

```
Tick süresi (T) = 30 saniye   (heartbeat_manager döngüsü)
3 loop miss    → BIN_OFFLINE

Bin, kaç saniye sessiz kalırsa OFFLINE olur?
→ 3 × 30 sn = 90 saniye (1.5 dakika)
```

### 6.2 Firmware'de Uygun Heartbeat Aralığı

ESP32'nin uyku süresi şu kısıtı sağlamalıdır:

$$T_{sleep} < T_{tick} \times 3 = 30 \times 3 = 90 \text{ sn}$$

Güç bütçesi ve bu kısıt dengelendiğinde optimal değer **60 saniye** olarak seçilir:

| Parametre | Değer | Gerekçe |
|---|---|---|
| Deep sleep süresi | 60 sn | 90 sn limitinin altında, 50% güvenlik payı |
| Güçte uyku akımı | 10 µA | Kabul edilebilir pil tüketimi |
| Backend miss toleransı | 3 loop (90 sn) | 1 paket kaybında bile OFFLINE olmaz |

```
Zaman   t=0     t=60    t=120   t=150
        │       │       │       │
ESP32:  [Ping] [Ping]  [Ping]  [Ping]  (her 60 sn)
Backend: o─────o───────o───────o       (her 30 sn tick)
Miss:    0     0       0       0       → ONLINE kalır

Paket kaybı olursa:
        [Ping]  XKAYBX  [Ping]
Backend: o─────o───────o
Miss:    0     1       0       → ONLINE kalır (3'e ulaşmadı)
```

### 6.3 Heartbeat ile fill güncellemesini ayırma

Her deep sleep uyanışında **her zaman** heartbeat atılır. Ama fill level güncellemesi yalnızca **değişim varsa** atılır:

```
Boot N  →  fill = LOW  (önceki: LOW)    → sadece /heartbeat
Boot N+1→  fill = MEDIUM (önceki: LOW) → /update-fill + /heartbeat
Boot N+2→  fill = MEDIUM (önceki: MEDIUM)→ sadece /heartbeat
```

Bu strateji ağ trafiğini minimize eder ve backend'e gereksiz `MEDIUM→MEDIUM` tekrar güncellemesi göndermeyi önler.

---

## 7. API Entegrasyonu — HTTP Payload'ları

### 7.1 `POST /update-fill`

**Endpoint:** `http://{BACKEND_HOST}:8000/update-fill`  
**Method:** POST  
**Content-Type:** application/json

**Request:**
```json
{
  "bin_id": "WMS4505",
  "fill_level": "HIGH"
}
```

**Başarılı Response (200):**
```json
{
  "bin_id": "WMS4505",
  "fill_level": "HIGH",
  "status": "ANOMALY",
  "anomaly_detected": true,
  "event_type": "OVERFLOW_RISK",
  "event_id": 1234
}
```

**Hata Durumları (firmware tarafı):**

| HTTP Kodu | Anlamı | Firmware Aksiyonu |
|---|---|---|
| `200` | Başarılı | LED yeşil blink, devam et |
| `422` | fill_level enum dışı | Bu hiç olmaz (firmware enum kontrol ediyor), log yaz |
| `404` | bin_id tanımsız | EEPROM'u kontrol et, bin_id yanlış |
| `500` | Backend hatası | Retry (bkz §8) |
| Timeout | WiFi/ağ sorunu | Retry, sonra deep sleep |

### 7.2 `POST /heartbeat`

**Endpoint:** `http://{BACKEND_HOST}:8000/heartbeat`  
**Method:** POST  
**Content-Type:** application/json

**Request:**
```json
{
  "bin_id": "WMS4505"
}
```

**Başarılı Response (200):**
```json
{
  "bin_id": "WMS4505",
  "acknowledged": true,
  "timestamp": "2026-03-10T09:30:00Z"
}
```

### 7.3 bin_id Yapılandırması

Her ESP32 modülü bir Dublin CSV bin_id'si ile eşleştirilir. Bu değer firmware'e iki yöntemden biriyle yazılır:

**Seçenek A — EEPROM'a sabit yazma (önerilir, demo için):**
```c
#include <EEPROM.h>
// Flash sırasında bir kez çalıştırılır
EEPROM.begin(32);
EEPROM.writeString(0, "WMS4505");
EEPROM.commit();
```

**Seçenek B — WiFi Provisioning (production için):**
ESP32 ilk boot'ta kendi AP'sini açar → Tarayıcıdan bin_id ve WiFi şifresi girilir → EEPROM'a kaydedilir. `WiFiManager` kütüphanesi bu akışı 20 satır kodda sağlar.

---

## 8. Hata Yönetimi ve Yeniden Bağlantı

### 8.1 WiFi Bağlantı Stratejisi

```
WiFi.begin(SSID, PASSWORD)

Döngü:
  Bağlantı bekle (500ms)
  attempt++
  if attempt >= 20 (10 sn):
    WiFi.disconnect()
    Hata log yaz (Serial)
    LED kırmızı blink (3×)
    Deep sleep (5 dk)  ← Normal 60 sn yerine daha uzun bekle
    return

Bağlandı → devam et
```

### 8.2 HTTP Retry Stratejisi

Ağ katmanındaki geçici hatalara karşı **exponential backoff** uygulanır:

```
Deneme 1 → 200? → Bitti
     ↓ Başarısız
     Bekle 2 sn
Deneme 2 → 200? → Bitti
     ↓ Başarısız
     Bekle 4 sn
Deneme 3 → 200? → Bitti
     ↓ Başarısız
     Tüm denemeler tükendi → deep sleep (normal aralık)
     (heartbeat_manager zaten binary olarak izliyor,
      1-2 miss toleranslı)
```

### 8.3 Sensör Hata Tespiti

| Durum | Belirti | Aksyon |
|---|---|---|
| Sensör bağlı değil / probe kopuk | `duration == 0` veya `distance > 600` | HTTP isteği atma, hata logla |
| Sensör yüzey yansıması (su/köpük) | Ölçümler tutarsız (std dev > 10 cm) | Medyan filtresi bu durumun çoğunu yakalar |
| Konteynır taşmış (distance < 5 cm) | `fill_pct > 100%` | Yine de `HIGH` gönder (sınırlandır) |
| Voltaj düşük (pil bitmek üzere) | ADC ölçümünde 3.3V < 2.9V | `LOW_BATTERY` flag'ini detail JSON'a ekle (opsiyonel gelişme) |

---

## 9. Güç Tüketimi ve Deep Sleep Stratejisi

### 9.1 Aktif/Uyku Döngüsü

```
     BOOT        ÖLÇÜM     HTTP TX    DEEP SLEEP
      │             │          │          │
  ────┤░░░░░░░░░░░░░│░░░░░░░░░░│──────────┤
      │←── ~1 sn ──►│←── 2sn ─►│◄── 57 sn─►│
      │  WiFi bağlantı          │          │
      220 mA          200 mA        10 µA
```

**Enerji hesabı (tek döngü, 60 sn periyot):**

$$E_{döngü} = (220 \text{ mA} \times 1 \text{ sn}) + (200 \text{ mA} \times 2 \text{ sn}) + (0.01 \text{ mA} \times 57 \text{ sn})$$
$$= 220 + 400 + 0.57 \approx 620 \text{ mAms} = 0.172 \text{ mAh}$$

**Günlük tüketim:** $(60 \times 60 / 60) \times 0.172 = 60 \times 0.172 = 10.33 \text{ mAh/gün}$

**2200 mAh pil ömrü:** $2200 / 10.33 ≈ 213 \text{ gün}$ (~7 ay)

### 9.2 Deep Sleep Konfigürasyonu

```c
#define SLEEP_DURATION_SEC 60

// 60 saniyelik deep sleep timer
esp_sleep_enable_timer_wakeup(SLEEP_DURATION_SEC * 1000000ULL);  // µs
esp_deep_sleep_start();
// Bu satırdan sonrası çalışmaz — ESP32 tamamen kapanır
```

> **Not:** Deep sleep'te WiFi, BLE, tüm periferaller kapatılır. Sadece RTC ve ULP core çalışır. `RTC_DATA_ATTR` değişkenleri yaşar.

---

## 10. Firmware Kaynak Kodu (Tam)

### 10.1 `ecohaul_sensor.ino`

```cpp
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <EEPROM.h>
#include <algorithm>

// ───────────────────────────────────────────────────
// YAPILANDIRMA — Kendi değerlerinizle doldurun
// ───────────────────────────────────────────────────
const char* WIFI_SSID       = "YOUR_SSID";
const char* WIFI_PASSWORD   = "YOUR_PASSWORD";
const char* BACKEND_HOST    = "192.168.1.100";   // FastAPI sunucu IP
const int   BACKEND_PORT    = 8000;
const char* BIN_ID          = "WMS4505";         // Dublin CSV bin_id

// ───────────────────────────────────────────────────
// DONANIM TANIMLARI
// ───────────────────────────────────────────────────
#define TRIG_PIN           5
#define ECHO_PIN           18
#define LED_PIN            2    // Dahili LED (isteğe bağlı)
#define BIN_HEIGHT_CM      100  // Konteyner yüksekliği (cm) — ölçerek gir
#define SLEEP_DURATION_SEC 60   // 60 sn deep sleep (< 90 sn — 3-loop miss limitinin altında)
#define WIFI_TIMEOUT_MS    10000
#define HTTP_TIMEOUT_MS    5000
#define SAMPLE_COUNT       5    // Medyan filtresi için ölçüm sayısı

// ───────────────────────────────────────────────────
// RTC MEMORY — Deep sleep arası kalıcı veri
// ───────────────────────────────────────────────────
RTC_DATA_ATTR char  last_fill_level[10] = "LOW";
RTC_DATA_ATTR int   boot_count          = 0;

// ───────────────────────────────────────────────────
// ULTRASONIK ÖLÇÜM
// ───────────────────────────────────────────────────
float measureDistance() {
    digitalWrite(TRIG_PIN, LOW);
    delayMicroseconds(2);
    digitalWrite(TRIG_PIN, HIGH);
    delayMicroseconds(10);   // ≥ 10µs trigger pulse
    digitalWrite(TRIG_PIN, LOW);

    long duration = pulseIn(ECHO_PIN, HIGH, 35000);  // 35ms timeout (~6m max)
    if (duration == 0) return -1;  // Sensör okuma hatası
    return duration * 0.0343f / 2.0f;
}

float measureStable() {
    float samples[SAMPLE_COUNT];
    int valid = 0;

    for (int i = 0; i < SAMPLE_COUNT; i++) {
        float d = measureDistance();
        if (d > 2 && d < 600) {
            samples[valid++] = d;
        }
        delay(60);  // Sensör toparlanma süresi
    }

    if (valid < 3) return -1;  // Yeterli geçerli ölçüm yok

    // Insertion sort (küçük dizi, overhead minimal)
    for (int i = 1; i < valid; i++) {
        float key = samples[i];
        int j = i - 1;
        while (j >= 0 && samples[j] > key) {
            samples[j + 1] = samples[j--];
        }
        samples[j + 1] = key;
    }
    return samples[valid / 2];  // Medyan
}

// ───────────────────────────────────────────────────
// DOLULUK SINIFLAMA
// ───────────────────────────────────────────────────
String classifyFillLevel(float distance_cm) {
    if (distance_cm < 0) return "ERROR";
    float fill_pct = ((float)BIN_HEIGHT_CM - distance_cm) / BIN_HEIGHT_CM * 100.0f;
    fill_pct = constrain(fill_pct, 0.0f, 100.0f);

    if (fill_pct <= 33.0f) return "LOW";
    if (fill_pct <= 66.0f) return "MEDIUM";
    return "HIGH";
}

// ───────────────────────────────────────────────────
// WiFi BAĞLANTISI
// ───────────────────────────────────────────────────
bool connectWiFi() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - start > WIFI_TIMEOUT_MS) {
            WiFi.disconnect(true);
            return false;
        }
        delay(500);
    }
    return true;
}

// ───────────────────────────────────────────────────
// HTTP POST — Yeniden Deneme Mantığı
// ───────────────────────────────────────────────────
bool httpPost(const String& endpoint, const String& payload) {
    HTTPClient http;
    String url = "http://" + String(BACKEND_HOST) + ":" +
                 String(BACKEND_PORT) + endpoint;

    int delays_ms[] = {2000, 4000};  // Exponential backoff
    for (int attempt = 0; attempt < 3; attempt++) {
        http.begin(url);
        http.addHeader("Content-Type", "application/json");
        http.setTimeout(HTTP_TIMEOUT_MS);

        int code = http.POST(payload);
        http.end();

        if (code == 200) return true;

        Serial.printf("[HTTP] %s  Deneme %d  Kod: %d\n",
                      endpoint.c_str(), attempt + 1, code);

        if (attempt < 2) delay(delays_ms[attempt]);
    }
    return false;
}

// ───────────────────────────────────────────────────
// /update-fill
// ───────────────────────────────────────────────────
bool sendFillUpdate(const String& fill_level) {
    DynamicJsonDocument doc(128);
    doc["bin_id"]     = BIN_ID;
    doc["fill_level"] = fill_level;
    String payload;
    serializeJson(doc, payload);

    Serial.printf("[FILL] Gönderiliyor: %s\n", payload.c_str());
    return httpPost("/update-fill", payload);
}

// ───────────────────────────────────────────────────
// /heartbeat
// ───────────────────────────────────────────────────
bool sendHeartbeat() {
    DynamicJsonDocument doc(64);
    doc["bin_id"] = BIN_ID;
    String payload;
    serializeJson(doc, payload);

    Serial.printf("[HB] Heartbeat: %s\n", BIN_ID);
    return httpPost("/heartbeat", payload);
}

// ───────────────────────────────────────────────────
// SETUP — Her boot/wake sonrası bir kez çalışır
// ───────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    boot_count++;
    Serial.printf("\n=== EcoHaul Sensor Boot #%d ===\n", boot_count);

    pinMode(TRIG_PIN, OUTPUT);
    pinMode(ECHO_PIN, INPUT);
    pinMode(LED_PIN, OUTPUT);

    // 1. Ölçüm yap
    float distance  = measureStable();
    String cur_fill = classifyFillLevel(distance);

    Serial.printf("[SENSOR] Mesafe: %.1f cm  →  %s\n",
                  distance, cur_fill.c_str());

    if (cur_fill == "ERROR") {
        Serial.println("[ERROR] Sensör okuma hatası — HTTP atlanıyor");
        goto SLEEP;
    }

    // 2. WiFi bağlan
    Serial.println("[WIFI] Bağlanıyor...");
    if (!connectWiFi()) {
        Serial.println("[WIFI] Bağlantı BAŞARISIZ");
        goto SLEEP;
    }
    Serial.printf("[WIFI] Bağlandı. IP: %s\n",
                  WiFi.localIP().toString().c_str());
    digitalWrite(LED_PIN, HIGH);

    // 3. Doluluk değişimi varsa /update-fill gönder
    if (strcmp(cur_fill.c_str(), last_fill_level) != 0) {
        Serial.printf("[FILL] Değişim: %s → %s\n",
                      last_fill_level, cur_fill.c_str());
        if (sendFillUpdate(cur_fill)) {
            // Başarılıysa son değeri RTC'ye kaydet
            strncpy(last_fill_level, cur_fill.c_str(),
                    sizeof(last_fill_level) - 1);
        }
    } else {
        Serial.println("[FILL] Değişim yok — update-fill atlandı");
    }

    // 4. Her boot'ta heartbeat gönder (ALWAYS)
    sendHeartbeat();

    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);
    digitalWrite(LED_PIN, LOW);

SLEEP:
    Serial.printf("[SLEEP] %d sn deep sleep başlıyor...\n",
                  SLEEP_DURATION_SEC);
    Serial.flush();
    esp_sleep_enable_timer_wakeup(
        (uint64_t)SLEEP_DURATION_SEC * 1000000ULL);
    esp_deep_sleep_start();
}

void loop() {
    // Deep sleep kullanıldığında loop() hiç çalışmaz
}
```

### 10.2 Gerekli Kütüphaneler (Arduino IDE / PlatformIO)

| Kütüphane | Kaynak | Versiyon |
|---|---|---|
| `WiFi` | ESP32 Arduino Core (dahili) | — |
| `HTTPClient` | ESP32 Arduino Core (dahili) | — |
| `ArduinoJson` | Arduino Library Manager | 7.x |
| `EEPROM` | ESP32 Arduino Core (dahili) | — |

**PlatformIO `platformio.ini`:**
```ini
[env:esp32dev]
platform  = espressif32
board     = esp32dev
framework = arduino

lib_deps =
    bblanchon/ArduinoJson@^7.0.0

monitor_speed = 115200
upload_speed  = 921600
```

---

## 11. Simülatör ↔ Gerçek Donanım Karşılaştırması

Firmware ve `iot_simulator.py` aynı API kontratını kullanır. Backend bunlar arasındaki farkı **göremez**.

| Özellik | `iot_simulator.py` | ESP32 Firmware |
|---|---|---|
| Doluluk kaynağı | `random.random() < fill_probability[hour]` | Ultrasonik mesafe ölçümü |
| Dolma akışı | LOW→MEDIUM, MEDIUM→HIGH (adım adım) | Fiziksel atık birikimi (aynı akış) |
| Heartbeat | Her döngüde tüm bin'lere toplu | Her 60 sn, bin'e özgü bireysel |
| `bin_id` | Dublin CSV'den rastgele seçim | EEPROM'a yazılı sabit değer |
| Hata simülasyonu | Satır yorumu ile kapama | Gerçek WiFi/sensör arızası |
| `/update-fill` payload | Aynı JSON şeması | Aynı JSON şeması |
| `/heartbeat` payload | Aynı JSON şeması | Aynı JSON şeması |
| Backend anomali tepkisi | Aynı (FILL_SKIP, SUSPICIOUS_EMPTYING…) | Aynı |

**Geliştirme sırasında híbrit kullanım:** Bazı bin'ler simülatörden, bazıları gerçek ESP32'den veri gönderir. Backend her ikisini de aynı pipeline'dan geçirir.

---

## 12. Kurulum ve Flash Adımları

### 12.1 Gereksinimler

- Arduino IDE 2.x veya PlatformIO (VS Code eklentisi)
- ESP32 Arduino Core: Arduino IDE → Board Manager → "esp32 by Espressif Systems" ≥ 3.x
- USB-A to Micro-USB kablo (data capable, sadece şarj değil)
- CP2102 veya CH340 USB-UART sürücüsü (Windows'ta gerekebilir)

### 12.2 Windows'ta Sürücü Kurulumu

```
1. ESP32'yi USB'ye tak
2. Cihaz Yöneticisi → Portlar → CP210x (veya CH340) seri port görünür
3. Sürücü yoksa:
   CP2102: https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers
   CH340:  http://www.wch-ic.com/downloads/CH341SER_EXE.html
4. COM port numarasını not et (Arduino IDE'de Tools > Port'tan seç)
```

### 12.3 Yapılandırma

`ecohaul_sensor.ino` dosyasının üst kısmındaki sabitleri doldurun:

```cpp
const char* WIFI_SSID       = "EvWifi";         // Ağ adı
const char* WIFI_PASSWORD   = "sifre123";        // Ağ şifresi
const char* BACKEND_HOST    = "192.168.1.100";  // FastAPI'nin çalıştığı IP
const int   BACKEND_PORT    = 8000;
const char* BIN_ID          = "WMS4505";         // Dublin'deki gerçek bin_id
#define BIN_HEIGHT_CM        100                  // Konteyner içi yüksekliği ölç
```

> **Backend IP Tespiti:** FastAPI çalışan bilgisayarın IP'si için PowerShell'de `ipconfig` → "Wireless LAN adapter Wi-Fi" altındaki IPv4 adresi. Örn: `192.168.1.100`

### 12.4 Flash Adımları (Arduino IDE)

```
1. Tools > Board > ESP32 Arduino > "ESP32 Dev Module"
2. Tools > Port > "COMx" (cihaz yöneticisinde gördüğünüz port)
3. Tools > Upload Speed > 921600
4. Sketch > Upload (Ctrl+U)
5. Yükleme başlamıyorsa: BOOT butonuna basılı tut → Upload başlar → bırak
6. Upload tamamlandı → Tools > Serial Monitor (115200 baud)
```

### 12.5 Beklenen Seri Çıktı

```
=== EcoHaul Sensor Boot #1 ===
[SENSOR] Mesafe: 72.3 cm  →  LOW
[WIFI] Bağlanıyor...
[WIFI] Bağlandı. IP: 192.168.1.105
[FILL] Değişim: LOW → LOW — değişim yok — update-fill atlandı
[HB] Heartbeat: WMS4505
[SLEEP] 60 sn deep sleep başlıyor...

=== EcoHaul Sensor Boot #2 ===
[SENSOR] Mesafe: 54.1 cm  →  MEDIUM
[WIFI] Bağlanıyor...
[WIFI] Bağlandı. IP: 192.168.1.105
[FILL] Değişim: LOW → MEDIUM
[FILL] Gönderiliyor: {"bin_id":"WMS4505","fill_level":"MEDIUM"}
[HB] Heartbeat: WMS4505
[SLEEP] 60 sn deep sleep başlıyor...
```

---

## 13. Test ve Doğrulama

### 13.1 Birim Testleri (Manuel)

| # | Test | Nasıl Yapılır | Beklenen Sonuç |
|---|---|---|---|
| T1 | Mesafe ölçüm doğruluğu | Sensörü düz yüzeyden bilinen mesafeye (30 cm) yerleştir | Serial: `~30 cm ± 3 cm` |
| T2 | LOW sınırı | Konteynerin 80 cm altında sensör | `fill_pct ≈ 20%` → `"LOW"` |
| T3 | MEDIUM sınırı | Konteynerin 50 cm altında | `fill_pct ≈ 50%` → `"MEDIUM"` |
| T4 | HIGH sınırı | Konteynerin 20 cm altında | `fill_pct ≈ 80%` → `"HIGH"` |
| T5 | WiFi bağlantı başarısı | Doğru SSID/şifre ile | Serial: `"Bağlandı. IP: ..."` |
| T6 | WiFi bağlantı başarısızlığı | Yanlış şifre | Serial: `"Bağlantı BAŞARISIZ"`, 5 dk sonra tekrar boot |
| T7 | `/update-fill` HTTP 200 | FastAPI çalışırken HIGH ölç | Serial: `[HTTP] Başarılı`, `event_log` tablosunda OVERFLOW_RISK |
| T8 | RTC memory kalıcılığı | Son gönderilen level ile bir sonraki boot uyumu | Değişim olmadığında `update-fill` gönderilmez |
| T9 | Medyan filtresi | Sensör önüne kısa süreliğine elinizi tutun | Tek aykırı ölçüm fill_level değiştirmez |
| T10 | Sensör kopukluğu | ECHO pinini çek | Serial: `"Sensör okuma hatası"`, HTTP gönderilmez |

### 13.2 Entegrasyon Doğrulaması

ESP32'yi çalıştırdıktan sonra FastAPI log'larından ve PostgreSQL'den doğrula:

```sql
-- Son 10 telemetri kaydı (bins tablosundaki doluluk geçmişi)
SELECT t.bin_id, t.fill_level, t.recorded_at
FROM telemetry t
WHERE t.bin_id = 'WMS4505'
ORDER BY t.recorded_at DESC
LIMIT 10;

-- Event log — ESP32'den gelen anomaliler
SELECT e.bin_id, e.event_type, e.detail, e.created_at
FROM event_log e
WHERE e.bin_id = 'WMS4505'
ORDER BY e.created_at DESC
LIMIT 10;

-- Son heartbeat (bins tablosunda is_active)
SELECT bin_id, is_active, fill_level
FROM bins
WHERE bin_id = 'WMS4505';
```

### 13.3 Doğrulama Senaryosu — Demo Önü Checklist

| # | Kontrol | Geçer Kriteri |
|---|---|---|
| D1 | ESP32 seri çıktısı | Her 60 sn'de boot mesajı görünüyor |
| D2 | WiFi bağlantısı | Her boot'ta IP adresi alınıyor |
| D3 | Heartbeat | PostgreSQL `bins.is_active = TRUE` (bin online) |
| D4 | Doluluk artışı (elle) | Konteynere nesne koy → Serial `MEDIUM` → PostgreSQL `telemetry` kaydı |
| D5 | Frontend harita | Bin rengi değişiyor (yeşil → sarı → kırmızı) |
| D6 | HIGH anomali | Bin'i HIGH'a getir → dashboard alert görünüyor |
| D7 | Offline tespiti | ESP32'yi kapat → 3 loop (90 sn) sonra bin gri |
| D8 | Tekrar online | ESP32'yi aç → bin gri'den çıkıyor |

---

*Bu doküman ESP32 firmware geliştirmesi sırasında güncel tutulacaktır. Doluluk eşik değerleri (LOW/MEDIUM/HIGH sınır yüzdeleri) gerçek Dublin konteynırı ölçümleri ile kalibre edilerek güncellenecektir.*
