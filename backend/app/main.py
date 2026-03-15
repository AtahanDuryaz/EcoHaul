from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .database import get_db
from .schemas import BinOut, BinsSummaryOut
from .services.bins_service import fetch_bins, fetch_summary

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
