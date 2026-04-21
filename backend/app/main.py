from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .database import get_db
from .schemas import AnomalyEventOut, BinOut, BinsSummaryOut, HeartbeatIn, StateChangeIn
from .services.anomaly_service import fetch_recent_anomalies
from .services.bins_service import fetch_bins, fetch_summary, log_heartbeat, log_state_change

app = FastAPI(title="EcoHaul Week 1 API")

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
    """Return recent anomaly events for inspection in the UI."""

    return fetch_recent_anomalies(db, limit=limit)


@app.post("/api/devices/{bin_id}/state-change")
def post_state_change(
    bin_id: str,
    payload: StateChangeIn,
    db: Session = Depends(get_db),
) -> dict:
    try:
        log_state_change(db, bin_id, payload)
    except Exception as exc:  # pragma: no cover
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
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"status": "ok"}
