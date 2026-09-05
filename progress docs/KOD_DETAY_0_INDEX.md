# EcoHaul — Detaylı Kod Açıklaması (Tüm Proje)

Bu seri, EcoHaul projesinin **tüm kodunu** gerçek kod bloklarıyla, "şu method şunu yapıyor /
şurası önemli" tarzında, satır satır açıklar. Bitirme savunması ve rapor için referans niteliğindedir.

## Okuma Sırası

| # | Dosya | Kapsam |
|---|-------|--------|
| 1 | [KOD_DETAY_1_API_VE_VERITABANI.md](KOD_DETAY_1_API_VE_VERITABANI.md) | `init.sql`, `database.py`, `schemas.py`, `main.py`, `bins_service.py`, `anomaly_service.py` |
| 2 | [KOD_DETAY_2_DPET_ALGORITMA.md](KOD_DETAY_2_DPET_ALGORITMA.md) | `dpet.py` — 6 katmanlı dinamik dispatch algoritması |
| 3 | [KOD_DETAY_3_ENVIRONMENT_PREDICTOR.md](KOD_DETAY_3_ENVIRONMENT_PREDICTOR.md) | `environment.py` (talep modeli), `predictor.py` (K-means zone + öğrenme) |
| 4 | [KOD_DETAY_4_SIMULASYON_MOTORU.md](KOD_DETAY_4_SIMULASYON_MOTORU.md) | `simulation_engine.py` — iki paralel dünya, tick döngüsü, dispatch katmanları |
| 5 | [KOD_DETAY_5_ESP32_VE_FRONTEND.md](KOD_DETAY_5_ESP32_VE_FRONTEND.md) | `routers/simulation.py`, `ESP32-Sensor.ino`, React frontend tümü |
| 6 | [KOD_DETAY_6_SABIT_ROTA_ALGORITMALARI.md](KOD_DETAY_6_SABIT_ROTA_ALGORITMALARI.md) | `route_common.py`, `lo_dcs.py`, `aco_route.py`, `hho_route.py` — fixed dünyası için seçilebilir 3 literatür algoritması |

> **Not:** Daha kısa, "arama odaklı" özet için [KODU_ANLAMA.md](KODU_ANLAMA.md) dosyasına bakın.
> Bu seri ise her kod bloğunu açıkça gösterir ve detaylı açıklar.

## Sistemin 30 Saniyelik Özeti

EcoHaul, IoT destekli **akıllı atık toplama** sistemidir. Üç katman:

1. **Donanım (ESP32 + HC-SR04):** Kovaya monte ultrasonik sensör, saatlik ölçüm yapıp doluluk
   yüzdesini backend'e gönderir. Deep-sleep ile pil tasarrufu.
2. **Backend (FastAPI + PostgreSQL/PostGIS):** Sensör verisini saklar, anomali tespit eder ve
   bir **canlı simülasyon motoru** çalıştırır. Motor "iki paralel dünya" kurar:
   - **DPET algoritması** (ETF + trafik + kapasite bazlı dinamik dispatch)
   - **Sabit rotalar** (her sabah 06:00, geleneksel belediye yöntemi)
   - Aynı veriyle yarışıp KPI'larını (km, yakıt, CO₂, taşma, maliyet) karşılaştırır.
3. **Frontend (React + Leaflet):** Canlı harita, iki dünyayı yan yana gösteren operasyon
   merkezi, anomali geçmişi.

**Projenin akademik özü:** DPET algoritmasının sabit rotalara karşı yakıt/CO₂/maliyet tasarrufunu
ve taşma azalmasını ölçülebilir biçimde göstermek.
