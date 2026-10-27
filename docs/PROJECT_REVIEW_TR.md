# EcoHaul proje incelemesi ve junior CV rehberi

## Projede ne yaptın?

ESP32/HC-SR04 sensörlerinden FastAPI API'lerine, PostgreSQL/PostGIS veritabanına ve React/Leaflet dashboard'una uzanan bir akıllı atık yönetimi prototipi geliştirmişsin. Veri temizleme, WGS84 koordinat dönüşümü, telemetri kaydı, anomali kuralları, rota planlama ve karşılaştırmalı simülasyon aynı projede bulunuyor.

En güçlü taraf, doluluk, taşmaya kalan süre, trafik, kapasite ve coğrafi yakınlık gibi kısıtları rota kararına bağlaman. DPET aday seçimi, nearest-neighbor, kapasite kırpma ve 2-opt kullanıyor. LO-DCS, ACO ve HHO uyarlamaları karşılaştırma sağlıyor. Predictor, coğrafi kümeler ve dolum çevrimlerinin hareketli ortalamasıyla çalışıyor.

Bu değerlendirme kaynak koduna dayanır. Kişisel katkı kapsamı kesin olarak ayrıştırılamaz; aşağıdaki maddeleri yalnızca gerçekten üstlendiğin işler için kullan.

## CV için hazır metin

**EcoHaul — IoT Destekli Akıllı Atık Toplama ve Rota Planlama | Bitirme Projesi**
Python, FastAPI, PostgreSQL/PostGIS, React, Leaflet, ESP32, C++

- ESP32 sensör verilerini REST API üzerinden işleyerek konum, doluluk ve anomali takibi sağlayan full-stack bir atık yönetimi prototipi geliştirdim.
- Doluluk, taşmaya kalan tahmini süre ve araç kapasitesini kullanan dinamik sevk/rota planlama mantığı uyguladım; nearest-neighbor ve 2-opt ile rota iyileştirdim.
- LO-DCS, ACO ve HHO stratejilerini mesafe, yakıt, CO₂, maliyet ve taşma göstergeleriyle karşılaştıran simülasyon dashboard'u oluşturdum.
- Coğrafi veriyi temizleyip WGS84'e dönüştüren ve PostGIS'e aktaran veri hazırlama akışı geliştirdim.

Yer darsa ilk üç madde yeterli. Backend başvurularında API/veritabanını, full-stack başvurularında dashboard/entegrasyonu, gömülü yazılım başvurularında medyan filtre, RTC state, heartbeat ve deep sleep yaklaşımını öne çıkar.

### English version

**EcoHaul — IoT-assisted Waste Collection and Route Planning | Graduation Project**

- Built a full-stack prototype integrating ESP32 telemetry, FastAPI, PostgreSQL/PostGIS, and a React/Leaflet monitoring dashboard.
- Implemented capacity-aware dynamic dispatch and route refinement using nearest-neighbor and 2-opt heuristics.
- Integrated LO-DCS, ACO, and HHO adaptations into a comparative simulation tracking distance, fuel, emissions, cost, and overflow indicators.

### Kanıt gerektiren iddialar

Gerçek operasyonda yüzde tasarruf, üretim kullanımı, deep learning eğitimi, yayımlanmış makale veya global optimum iddiası koddan doğrulanmıyor. IEEE formatında LaTeX dosyası yayın kabulü anlamına gelmez. Tasarruf yazacaksan senaryo, veri sayısı, süre, seed, tekrar sayısı ve karşılaştırılan stratejiyle birlikte sonuç dosyasını paylaş.

## Öncelikli geliştirme önerileri

1. **Tekrarlanabilir deney:** Motor, çevre, kümeleme ve algoritmalar için ayrı RNG nesneleri kullan. Aynı talep/anomali olaylarını tüm stratejilere uygula; çoklu seed sonuçlarının ortalamasını ve dağılımını raporla. Global rastgelelik ve dünya-seçimli anomaliler karşılaştırmayı etkileyebilir.
2. **Tahmin doğrulaması:** Predictor yalnızca EMPTIED→OVERFLOW çevrimlerinden öğreniyor. Erken toplanan kutuları da değerlendiren yöntem geliştir; bağımsız veride ETF hatasını ölç. Simülasyonun fill-rate parametresini fallback kullanmak gerçek dünya başarısını kanıtlamaz.
3. **Veri bütünlüğü:** Bilinmeyen bin_id için telemetriyi reddet; foreign key ve giriş sınırları ekle. Anomali servisindeki geniş exception blokları transaction hatalarını saklayabilir; savepoint/rollback ve yapılandırılmış log kullan.
4. **API güvenliği:** Cihaz kimliği, token doğrulama, rate limit, izinli CORS listesi ve iç SQL ayrıntısını göstermeyen hata yanıtları ekle. Geçersiz hız isteği 422 dönmeli.
5. **Kurulum ve CI:** Docker Compose, migration, GitHub Actions build/test ve yapılandırma doğrulaması ekle. Label script'i şu anda ayrıca çalıştırılmalı.
6. **Eşzamanlılık:** Global motor process belleğinde; çok worker farklı simülasyonlar oluşturabilir. Thread üzerinden algoritma değiştirme ile start/reset yarışlarını kilitle. CPU yoğun işleri görev kuyruğuna taşı; SSE/WebSocket seçeneğini değerlendir.
7. **Sensör retry:** Başarısız HTTP gönderiminden sonra rtc_lastLevelInt güncelleniyor; değişim sonraki uyanmada tekrar gönderilmeyebilir. Son ölçülen ve son başarıyla gönderilen durumu ayır; kalıcı retry ve fiziksel kalibrasyon testleri ekle.
8. **Gerçek yol modeli:** Haversine yerine yol ağı mesafe/süre matrisi, gerçek kapasite birimleri ve kalibre yakıt modeli kullan. Varsayımları sonuçlarla birlikte göster.
9. **Arayüz bakımı:** Aktif giriş SimulationPage. Eski App.jsx mount edilmiyor ve export edilmeyen fetchRoutePreview fonksiyonunu import ediyor; kullanılmadan önce entegrasyonu tamamlanmalı. Mobil görünüm ve hata durumlarını doğrula.
10. **Portföy:** Kısa demo videosu, deney CSV'si ve doğrulanmış veri kaynağı/lisans bilgisi ekle. Katkı sahipliği netleştikten sonra açık kaynak lisansı seç.

## Yayın hazırlığı

README, kurulum sırası, örnek yapılandırma ve CV rehberi eklendi. ESP32 Wi-Fi bilgileri ignore edilen config.local.h dosyasına ayrıldı. Kök .env ve kişisel akademik PDF Git takibinden çıkarılırken yerel dosyalar korunur. label_bins.py import yolu düzeltildi. Rota kapsamı, seed tekrarlanabilirliği ve predictor öğrenme/reset kontrolleri eklendi.

Kok .env ve ESP32 Wi-Fi bilgileri uzak depodaki onceki commitlerde bulunuyor. Guncel agactan kaldirmak gecmisi temizlemez. Gercek veritabani ve Wi-Fi parolalarini degistir. Bu calisma Git gecmisini yeniden yazmaz. Yerel ESP32 ayarlari ignore edilen config.local.h dosyasinda korunur.
