# EcoHaul Week 1 Backend

## 1) Install dependencies

```powershell
cd backend
../.venv/Scripts/python.exe -m pip install -r requirements.txt
```

## 2) Run dataset pipeline

```powershell
cd ..
.venv/Scripts/python.exe backend/scripts/clean_bins.py
.venv/Scripts/python.exe backend/scripts/transform_bins_to_wgs84.py
.venv/Scripts/python.exe backend/scripts/validate_bins.py
```

## 3) Configure database

- Install PostgreSQL and PostGIS
- Copy `.env.example` to `.env` and set `DATABASE_URL`
- Run schema and load script:

```powershell
.venv/Scripts/python.exe backend/scripts/load_bins_to_db.py
```

## 4) Start API

```powershell
cd backend
../.venv/Scripts/python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
