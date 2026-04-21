# EcoHaul Haritayı Çalıştırma Adımları (Tek Tek)

Bu dosya, sistemin çalışıp haritanın görüntülenmesi için gerekli adımları sırasıyla verir.

## 1) Ön koşulları hazırla

- Python 3.11+ kurulu olsun.
- Node.js 18+ kurulu olsun.
- PostgreSQL + PostGIS kurulu olsun.
- Proje klasöründesin: `c:\Users\ataka\Desktop\Bitirme Projesi EcoHaul`

---

## 2) Python sanal ortamını (venv) oluştur ve aktif et

PowerShell:

```powershell
cd "c:\Users\ataka\Desktop\Bitirme Projesi EcoHaul"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> Eğer venv zaten varsa sadece aktivasyon komutunu çalıştırman yeterli.

---

## 3) Backend bağımlılıklarını kur

```powershell
cd backend
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

---

## 4) Backend ortam değişkenini ayarla (.env)

`backend\.env.example` dosyasını `backend\.env` olarak kopyala.

PowerShell:

```powershell
Copy-Item .env.example .env
```

`backend\.env` içinde `DATABASE_URL` değerini kendi PostgreSQL kullanıcı/parola bilgine göre kontrol et:

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/ecohaul
```

---

## 5) Veri hazırlama pipeline adımlarını çalıştır

Proje kök dizinine geçip sırayla çalıştır:

```powershell
cd ..
.\.venv\Scripts\python.exe backend\scripts\clean_bins.py
.\.venv\Scripts\python.exe backend\scripts\transform_bins_to_wgs84.py
.\.venv\Scripts\python.exe backend\scripts\validate_bins.py
```

Bu adım sonunda `backend/data/bins_wgs84.csv` dosyası oluşmuş olmalı.

---

## 6) Veriyi veritabanına yükle

```powershell
.\.venv\Scripts\python.exe backend\scripts\load_bins_to_db.py
```

Başarılıysa terminalde benzer bir çıktı görürsün:

- `Loaded bins: ...`

---

## 7) Backend API’yi başlat (Terminal-1)

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Kontrol:
- Tarayıcıda `http://localhost:8000/health` aç.
- `{"status":"ok"}` dönüyorsa backend hazır.

---

## 8) Frontend bağımlılıklarını kur (Terminal-2)

Yeni bir terminal aç:

```powershell
cd "c:\Users\ataka\Desktop\Bitirme Projesi EcoHaul\frontend"
npm install
```

---

## 9) Frontend’i çalıştır

```powershell
npm run dev
```

Terminalde verilen local adresi aç (genelde `http://localhost:5173`).

---

## 10) Haritanın geldiğini doğrula

Ekranda:
- "EcoHaul - Hafta 1 MVP" başlığı,
- üstte özet değerler (Toplam Kutu / Offline),
- altta Leaflet haritası ve marker’lar görünmeli.

---

## Sorun olursa hızlı kontrol listesi

1. `http://localhost:8000/health` çalışıyor mu?
2. `backend/.env` içindeki `DATABASE_URL` doğru mu?
3. `load_bins_to_db.py` sonrası `Loaded bins:` çıktısı alındı mı?
4. Frontend için backend farklı port/adreste ise `frontend/.env` içine şu değeri ekle:

```env
VITE_API_URL=http://localhost:8000
```

5. Sonra frontend’i yeniden başlat:

```powershell
npm run dev
```