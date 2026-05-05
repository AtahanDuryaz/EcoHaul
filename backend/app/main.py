from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text

from .database import SessionLocal, get_db
from .routers import simulation
from .schemas import AnomalyEventOut, BinOut, BinsSummaryOut, HeartbeatIn, StateChangeIn
from .services.anomaly_service import fetch_recent_anomalies
from .services.bins_service import fetch_bins, fetch_summary, log_heartbeat, log_state_change
from .simulation_engine import engine


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


app = FastAPI(title="EcoHaul API", lifespan=lifespan)
app.include_router(simulation.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
