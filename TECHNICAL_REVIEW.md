# EcoHaul — Teknik İnceleme Dokümanı

> Bu doküman başka yapay zeka sistemlerinin projeyi bağımsız olarak inceleyebilmesi için
> hazırlanmıştır. Tüm algoritma kararları, parametreler ve tasarım gerekçeleri burada açıklanmıştır.

---

## 1. Proje Özeti

**EcoHaul**, Dublin şehri için akıllı çöp toplama optimizasyon simülasyonudur.
Gerçek zamanlı çalışan iki paralel dünya (algo vs. fixed) karşılaştırılır.
Hedef: DPET algoritmasının sabit rota sistemini **tüm KPI'larda aynı anda** geçmesidir.

**KPI'lar:** CO2 emisyonu (kg) | Yakıt sarfiyatı (L) | Operasyonel maliyet (₺) | Sefer sayısı | Toplam km | Taşma olayı sayısı

---

## 2. Veri Seti

**Kaynak:** Dublin City Council (DCC) açık veri — `dcc_public_bin_locations.csv`

| Alan | Açıklama |
|------|----------|
| `Bin_ID` | Benzersiz kimlik (örn. `WMS4505`) |
| `ELectoral_Area` | Seçim bölgesi / mahalle adı |
| `Bin_Type` | Fiziksel tip (Cast Iron, vb.) |
| `Irish_X` | Irish Transverse Mercator X koordinatı |
| `Irish_Y` | Irish Transverse Mercator Y koordinatı |

- **Toplam bin sayısı:** 3.424
- **Koordinat dönüşümü:** ITM → WGS84 (pyproj ile)
- **Simülasyonda kullanılan bin sayısı:** Tüm 3.424 bin
- **Coğrafi alan:** Dublin şehir merkezi ve çevresi (~53.3°N, 6.2°W)

### Simülasyon için türetilen özellikler

Her bin startup'ta aşağıdaki özellikler rastgele atanır ve iki dünya da aynı değeri paylaşır:

```python
FILL_RATE_RANGES = {
    "A": (12.0, 16.0),  # hızlı: ~6-8 sim saatte dolar  → %30 bin
    "B": (4.0,  8.0),   # orta : ~12-25 sim saatte dolar → %40 bin
    "C": (0.5,  1.5),   # yavaş: ~67-200 sim saatte dolar→ %30 bin
}
```

`fill_label` (A/B/C), `distance_label` (1/2/3 — depot'a uzaklık), `district_type` (mahalle region string'inden çıkarılan) startup'ta belirlenir ve simülasyon boyunca sabit kalır.

---

## 3. Sistem Mimarisi

```
backend/app/
├── simulation_engine.py   # Ana motor — iki dünya, tick loop, KPI
├── dpet.py                # DPET algoritması — 6 katman
├── predictor.py           # FillPredictor — K-means zone + ETF öğrenmesi
├── environment.py         # Phase 1 ortam — saatlik profil, event, gürültü
└── routers/simulation.py  # REST API — /start, /stop, /reset, /live-state, /live-kpis
```

**Simülasyon saati:** Her `0.2 gerçek saniye` = `speed_multiplier sim saniye` ilerler.
Varsayılan hız: `3600x` (1 gerçek saniye = 1 sim saat).

**Depot:** Dataset'teki en kuzey binin 0.005° (~550m) kuzeyine konumlandırılır.

---

## 4. Ortam Modeli — `environment.py`

### 4.1 District Tipleri

Her bin'e mahalle adından çıkarılan bir `DistrictType` atanır:

| Tip | Örnek bölge | Dolum piki |
|-----|-------------|------------|
| RESIDENTIAL | Konut mahalleleri | 18-20 arası |
| OFFICE | IFSC, iş merkezleri | 08-10 arası |
| MALL | AVM, alışveriş | 15-20 arası |
| UNIVERSITY | Kampüs, college | 09-14 arası |
| TOURIST | Temple Bar, oteller | 12-20 arası |

Tanınmayan bölge → Dublin dağılımına göre ağırlıklı rastgele (RESIDENTIAL %40, OFFICE %20, MALL %15, UNIVERSITY %15, TOURIST %10).

### 4.2 Saatlik Dolum Profili

Her tick'te:
```
effective_rate = base_rate × hourly_multiplier(district, hour) × event_multiplier × gaussian_noise(σ=0.10)
```

Örneğin RESIDENTIAL saat 19: çarpan = 2.0 → bin 2x hızlı dolar.
OFFICE saat 02: çarpan = 0.1 → neredeyse durur.

### 4.3 Event Sistemi

Rastgele aralıklarla (12-48 sim saat) geçici yüksek-talep olayları üretilir:

| Event | Çarpan | Süre | Etkilenen |
|-------|--------|------|-----------|
| concert | 1.8-3.0x | 4 sim saat | TOURIST, RESIDENTIAL |
| match | 2.0-3.5x | 3 sim saat | TOURIST, MALL |
| festival | 1.5-2.5x | 8 sim saat | TOURIST, MALL, RESIDENTIAL |
| sale | 1.5-2.0x | 6 sim saat | MALL |
| weekend | 1.2-1.6x | 48 sim saat | Tüm bölgeler |

---

## 5. DPET Algoritması — `dpet.py`

**DPET** = Dynamic Priority & Efficient Truck dispatch

### 5.1 Mimari — 6 Katman

```
TrafficModel → BinScorer → BinSelector → RouteBuilder → RouteEfficiency → Dispatcher
```

### 5.2 Katman 1 — TrafficModel

Saat bazlı trafik skoru [0.0, 1.0]:
```python
Rush hours  (7,8,9,17,18,19) → 0.80
Peak hours  (6,10,16,20)     → 0.50
Diğer saatler                → 0.20
```

### 5.3 Katman 2 — BinScorer

Her bin için 5 bileşenli öncelik skoru [0.0, 1.0]:

| Bileşen | Ağırlık | Formül | Gerekçe |
|---------|---------|--------|---------|
| fill_urgency | **0.40** | `(fill_pct/100)²` | Kritik bin'ler karesi alınarak ağırlıklandırılır |
| etf_urgency | **0.35** | `max(0, 1 - ETF/8h)` | 8 sim saatten az kaldıysa önem artar |
| proximity | **0.05** | `1 - (dist_label-1)/2` | Yakın bin tercih edilir |
| traffic_ok | **0.12** | `1 - traffic_score` | Az trafik = iyi sefer zamanı |
| density_norm | **0.08** | `min(1, nearby_bins/10)` | 1km içindeki yüksek-dolu bin sayısı |

**density_norm:** Bin'in 1km yarıçapında, doluluk ≥%65 olan bin sayısı / 10 olarak normalize edilir.
Kümeleri olan bin'ler hafifçe öncelik kazanır — aşırı ağırlık vermek izole acil bin'leri cezalandırır.

**ETF (Estimated Time to Full):**
```python
ETF_hours = (100.0 - fill_pct) / fill_rate
```

### 5.4 Katman 3 — BinSelector

Seçim kriterleri (trafik skoru > 0.70 → rush modu):

| Durum | Kriter |
|-------|--------|
| Acil | fill_pct ≥ 88% → MIN_DISPATCH atlanır |
| ETF kritik | ETF ≤ 3 sim saat → fill_pct eşiği atlanır |
| Normal saat | fill_pct ≥ 65% |
| Rush saat | fill_pct ≥ 85% |

`MIN_DISPATCH = 8`: 8'den az bin seçilebiliyorsa ve acil bin yoksa dispatch yapılmaz.
Bu eşik gereksiz kısa, dağınık seferleri önler.

### 5.5 Katman 4 — RouteBuilder

3 aşama:
1. **Nearest-Neighbor (NN) heuristic** — Depot'tan başlayarak her adımda en yakın bin
2. **Kapasite kırpması** — Hacimsel model ile kamyon dolduğunda dur
3. **Tam 2-opt** — Yakıt-ağırlıklı mesafeyi minimize eder

**Hacimsel kapasite modeli:**
```python
TRUCK_CAPACITY      = 1.0    # normalize
BIN_VOLUME_FRACTION = 0.05   # %100 dolu bin kamyonun %5'ini kullanır
bin_load = (fill_pct / 100.0) * BIN_VOLUME_FRACTION
```
Kamyon teorik olarak 20 tam dolu bin taşıyabilir; gerçekte karışık dolulukla çok daha fazla.

**Yakıt-ağırlıklı 2-opt:**
```python
cost_i = dist_i × (1 + FUEL_WEIGHT_FACTOR × i/n)
```
Kamyon her durağı geçtikçe ağırlaşır → sonraki bacaklar daha pahalı.
2-opt, hafif yükle uzun bacakları, ağır yükle kısa bacakları tercih eden rotalar üretir.

### 5.6 Katman 5 — RouteEfficiency

```python
efficiency = len(stops) / total_km
MIN_ROUTE_EFFICIENCY = 0.20  # bin/km
```
Acil bin olmayan, verimsiz rotalar (0.20 bin/km altı) gönderilmez.

### 5.7 Katman 6 — Dispatcher (dpet_dispatch)

```python
available_slots = max_fleet - active_truck_count
selected = select_bins(..., max_stops = ALGO_MAX_STOPS * available_slots)
```
Mevcut slot sayısı kadar kamyon için bin seçilir, `max_stops = 40` gruplarına bölünür.

---

## 6. FillPredictor — `predictor.py`

### 6.1 K-means++ Zone Ataması

Startup'ta bir kez çalışır:
- **N_ZONES = 12** mikro-zone (önceki: 6)
- **K-means++** başlangıç centroid seçimi (uzak noktalara bias)
- **25 Lloyd iterasyonu**
- Bin konumları değişmediği için reset'te tekrar çalıştırılmaz

Zone başına ortalama ~285 bin düşer.

### 6.2 Fill Cycle Öğrenmesi

```
EMPTIED eventi → son boşaltma sim_s kaydedilir
OVERFLOW eventi → (şimdiki_sim_s - son_EMPTIED) = cycle_s → rolling window'a eklenir
```

Max 8 cycle saklanır. 2+ gözlem varsa gerçek dolum süresi kullanılır, yoksa fallback `fill_rate`.

### 6.3 Adaptif Coverage Interval

Zone'daki bin'lerin medyan ETF'ine göre ziyaret sıklığı dinamik belirlenir:
```python
ratio = clamp(median_etf_h / base_interval_h, 0.25, 3.0)
adaptive_interval = BASE_INTERVAL_S * ratio
```

- A-label zone (median ETF ~4h) → interval = 20h × 0.25 = **5 sim saatte bir ziyaret**
- C-label zone (median ETF ~80h) → interval = 20h × 3.0 = **60 sim saatte bir ziyaret**

Sabit-frekans ziyaretlere kıyasla C-label zone'larda %66 daha az boş sefer.

---

## 7. Dispatch Katmanları — `simulation_engine.py`

Her 1 sim saatte bir `_job_dispatch_algo` çalışır. Dört katmanlı karar:

### Tier 0 — Priority Aging
%100 dolulukta ≥4 sim saat bekleyen bin'ler için **ekstra kamyon**.
Minimum 3 bin şartı. Zone kısıtı yok.

### Tier 1 — Acil Zone (ETF ≤ 2 saat)
Predictor'dan ETF ≤ 2 sim saat olan bin'ler zone bazında toplanır.
Zone'da ≥4 bin varsa dispatch tetiklenir.

### Tier 2 — Coverage Rotation (Adaptif)
Her zone'un son ziyaret üzerinden adaptif interval kontrolü.
Zone'da ≥30% dolu bin yoksa bile ziyaret damgası güncellenir.

### Fallback
Hiçbir tier dispatch üretmediyse ve ≥90% dolu bin varsa acil scatter sefer.

### Rota Genişletme

**Acil extension:** Mevcut kamyonlara ≥90% dolu bin'ler eklenir.
Kural: `extra_km / remaining_km ≤ 0.30`

**Koridor pickup (yeni):** Her kamyon rotasının bacaklarına 500m yakın, ≥70% dolu bin'ler tespit edilir ve `_insertion_km` ile mevcut rotaya eklenir.
Kural: `extra_km / remaining_km ≤ 0.20` (daha sıkı — zaten yakında olmalı)

**Fırsatçı toplama:** Dispatch edilen zone ile aynı zone'da, ≥60% dolu bin'ler rota uzatılmadan route'a eklenir.

---

## 8. Sabit Rota Baseline — `simulation_engine.py`

**Akademik temel:** Gillett & Miller (1974) Sweep Algorithm for VRP.

### Rota oluşturma (startup'ta bir kez):
1. Her bin için depot'tan açı hesapla: `atan2(lon - depot_lon, lat - depot_lat)`
2. Açıya göre sırala (radyal dilimler)
3. 20'lik gruplara böl
4. Her grup içinde Nearest-Neighbor sıralama (2-opt YOK)

Sweep algoritması her rotanın hem yakın hem uzak bin'ler içermesini sağlar.
**2-opt kasıtlı olarak eklenmedi** — fixed rota akademik olarak zayıf ama gerçek belediye sistemlerini temsil etmeli.

### Dispatch zamanı:
Her gün 06:00 sanal saatte tüm rotalar gönderilir.
Filo: MAX_FLEET_SIZE = 15 kamyon.
Kamyon tamamladıkça sıradaki rota devreye girer.

---

## 9. Temel Parametreler — Özet Tablosu

| Parametre | Değer | Nerede | Gerekçe |
|-----------|-------|--------|---------|
| MAX_FLEET_SIZE | 15 | simulation_engine | Her dünya için maksimum aktif kamyon |
| ALGO_MAX_STOPS | 40 | simulation_engine | Kapasite kırpması gerçek sınırı uygular |
| TRUCK_CAPACITY | 1.0 | dpet | Normalize hacimsel kapasite |
| BIN_VOLUME_FRACTION | 0.05 | dpet | Tam dolu bin = kamyonun %5'i |
| FUEL_WEIGHT_FACTOR | 0.8 | dpet | Ağırlıkla yakıt artışı |
| CO2_PER_KM | 0.28 kg | simulation_engine | Dizel kamyon emisyon faktörü |
| FUEL_PER_KM | 0.35 L | simulation_engine | Boş kamyon tüketimi |
| TRUCK_SPEED_KMH | 30 | simulation_engine | Şehir içi hız |
| SERVICE_SIM_MIN | 5 | simulation_engine | Durak başı servis süresi |
| N_ZONES | 12 | predictor | K-means mikro-zone sayısı |
| MIN_ZONE_BINS | 6 | predictor | Zone dispatch minimum bin |
| MIN_DISPATCH | 8 | dpet | Tek sefer için minimum bin |
| ETF_LEAD_TIME | 3.0h | dpet | Erken yakalama penceresi |
| _EMERGENCY_FILL | 88% | dpet | MIN_DISPATCH bypass eşiği |
| COVERAGE_INTERVAL_S | 20h (baz) | simulation_engine | Adaptif interval baz değeri |
| CORRIDOR_RADIUS_KM | 0.5 | simulation_engine | Koridor pickup yarıçapı |
| OPPORTUNISTIC_FILL | 60% | simulation_engine | Fırsatçı toplama eşiği |
| AGING_THRESHOLD_S | 4h | simulation_engine | Priority aging eşiği |

---

## 10. KPI Hesaplama

### Yakıt (ağırlık-duyarlı)
```python
fuel_leg_i = dist_i × FUEL_PER_KM × (1 + WEIGHT_MULTIPLIER × i/n)
fuel_return = dist_return × FUEL_PER_KM × (1 + WEIGHT_MULTIPLIER)
```

### Maliyet
```python
cost = DISPATCH_COST_TL(2000) + total_fuel × FUEL_PRICE_TL(45)
```

### Taşma
Tick bazlı: her bin %100'de olduğu her tick `overflow_events += 1`.
Bu metrik süre-bazlı → uzun süre %100'de kalan bin katlanarak sayar.

### Verimlilik (frontend) — Yük-ağırlıklı Rota Verimliliği
```python
# Backend: her bin boşaltıldığında
kpis["bins_collected"] += 1
kpis["load_collected"] += b.fill_pct   # 0–100 arası, boşaltma anındaki doluluk

# Frontend:
load_per_km = load_collected / distance_km   # yk/km birimi
efficiency  = min(100, round(load_per_km / 0.8))  # 80 yk/km → %100
```

**Neden anlamlı:** 15 adet %70 dolu bin > 20 adet %10 dolu bin.
Algoritma seçici toplar (yüksek ortalama doluluk → yüksek yk/km).
Fixed rota her sabah erken tüm şehri toplar, bin'lerin çoğu henüz %20-30 doluyken → düşük yk/km.
Bu metrik hem rota yoğunluğunu hem toplanan gerçek yükü aynı anda değerlendirir.

---

## 11. Karşılaştırma Sonuçları (Örnek — 403 vs 650 sefer)

| Metrik | Algo | Fixed | Fark |
|--------|------|-------|------|
| CO2 (kg) | 3399.5 | 4470.7 | **-1071.2 ✅** |
| Yakıt (L) | 6274.2 | 8441.1 | **-2166.9 ✅** |
| Maliyet (₺k) | 1088.3 | 1679.8 | **-591.5k ✅** |
| Sefer | 403 | 650 | **-247 ✅** |
| Km | 12141 | 15966 | **-3825 ✅** |
| Taşma | 365796 | 338925 | +26871 ❌ |

Son iki parametre değişikliği (`_EMERGENCY_FILL 95→88`, `_W_DENSITY 0.20→0.08`) taşmayı azaltmayı hedefler.

---

## 12. Bilinen Zorluklar ve Tasarım Kararları

### Taşma sayım paradoksu
Fixed rota her gün 06:00'da tüm bin'leri toplar → hiçbir bin 24 saatten fazla %100'de kalmaz.
Algo seçici davranır → nadir toplanan bin saatler boyu %100'de kalabilir.
Her tick %1 sayıldığı için uzun bekleme katlanarak cezalandırılır.

### Density skoru ve izole bin çelişkisi
Yoğunluk terimi cluster'ları ödüllendirir ama dağınık acil bin'leri cezalandırır.
Çözüm: `_W_DENSITY = 0.08` (düşük) + `_EMERGENCY_FILL = 88%` (erken bypass).

### Fixed rota kasıtlı zayıflama
2-opt uygulanmadı. Sweep algoritması uzak bin'leri de aynı rotaya katıyor.
Amaç: "gerçekçi belediye sistemi" temsili, mükemmel TSP çözümü değil.

### C-label zone boş sefer problemi
C-label bin'ler 67-200 sim saatte doluyor. Sabit 20h coverage interval bu zone'lara
boş sefer yapıyordu. Adaptif interval ile C-label zone'lar 40-60h'te bir ziyaret görür.

---

## 13. Dosya Referansları

| Dosya | Satır | İçerik |
|-------|-------|--------|
| [dpet.py](backend/app/dpet.py) | 1-378 | DPET 6-katman algoritması |
| [predictor.py](backend/app/predictor.py) | 1-275 | FillPredictor + K-means zone |
| [environment.py](backend/app/environment.py) | 1-284 | Ortam modeli + event sistemi |
| [simulation_engine.py](backend/app/simulation_engine.py) | 1-1005 | Ana simülasyon motoru |
| [routers/simulation.py](backend/app/routers/simulation.py) | - | REST API endpoints |
| [dataset/dcc_public_bin_locations.csv](dataset/dcc_public_bin_locations.csv) | - | DCC ham veri (3424 bin) |
| [scripts/analyze_fill.py](backend/scripts/analyze_fill.py) | - | Fill history CSV analiz scripti |

---

## 14. İnceleme Soruları (Başka AI için)

Aşağıdaki alanlarda bağımsız inceleme ve öneri beklenmektedir:

1. **Taşma azaltma:** `_EMERGENCY_FILL = 88%` ve `MIN_DISPATCH = 8` dengesi yeterli mi? Alternatif yaklaşım var mı?

2. **Density ağırlığı:** `_W_DENSITY = 0.08` izole bin problemini tam çözüyor mu? Yoksa density'yi bin seçim skoru yerine dispatch trigger'da mı kullanmalı?

3. **Adaptif interval alt sınır:** C-label zone için 60h üst limit mantıklı mı, yoksa mutlak bir taşma garantisi (örn. ETF ne olursa olsun max 48h) gerekiyor mu?

4. **Koridor pickup etkisi:** 500m yarıçap ve %20 sapma oranı doğru mu? Daha geniş koridor km artışını haklı kılar mı?

5. **Fixed baseline gücü:** Sweep + NN-only yeterince zayıf ama akademik açıdan savunulabilir mi? 2-opt eklemek "haksız" rekabet yaratır mı?

6. **Çok-amaçlı optimizasyon:** CO2/yakıt/km (verimliliğe odaklı) ile taşma (kapsama odaklı) iki çelişen amaç. Pareto-optimal çözüm ne olurdu?
