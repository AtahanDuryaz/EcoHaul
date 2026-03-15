from datetime import datetime

from pydantic import BaseModel


class BinOut(BaseModel):
    bin_id: str
    lat: float
    lon: float
    status: str
    region: str
    last_emptied_at: datetime | None


class BinsSummaryOut(BaseModel):
    total_bins: int
    offline_bins: int
    regions: dict[str, int]
