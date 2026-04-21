from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class FillLevelEnum(str, Enum):
    EMPTY = "EMPTY"
    FULL = "FULL"
    CRITICAL_FULL = "CRITICAL_FULL"
    SENSOR_ERROR = "SENSOR_ERROR"


class AnomalyType(str, Enum):
    OVERFLOW_RISK = "OVERFLOW_RISK"
    UNAUTHORIZED_EMPTY = "UNAUTHORIZED_EMPTY"
    BIN_OFFLINE = "BIN_OFFLINE"
    FILL_ANOMALY = "FILL_ANOMALY"
    SENSOR_FIXED_VALUE_ERROR = "SENSOR_FIXED_VALUE_ERROR"
    SENSOR_NOT_FOUND_ERROR = "SENSOR_NOT_FOUND_ERROR"


class BinOut(BaseModel):
    bin_id: str
    lat: float
    lon: float
    status: str
    region: str
    last_emptied_at: datetime | None
    fill_level: FillLevelEnum | None = None
    is_active: bool | None = None
    last_seen_at: datetime | None = None
    last_enum_transition: str | None = None
    last_enum_change_at: datetime | None = None
    last_event_type: str | None = None
    last_event_at: datetime | None = None


class BinsSummaryOut(BaseModel):
    total_bins: int
    offline_bins: int
    regions: dict[str, int]


class StateChangeIn(BaseModel):
    enum_state: FillLevelEnum
    median_distance_cm: float | None = None
    event_timestamp: datetime | None = None


class HeartbeatIn(BaseModel):
    current_enum: FillLevelEnum | None = None


class AnomalyEventOut(BaseModel):
    bin_id: str
    event_type: AnomalyType
    details: str | None = None
    created_at: datetime
