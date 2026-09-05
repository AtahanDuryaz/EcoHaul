from __future__ import annotations

from datetime import datetime, timedelta
import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..schemas import AnomalyEventOut, AnomalyType, FillLevelEnum


def log_anomaly_event(
    db: Session,
    bin_id: str,
    event_type: AnomalyType,
    details: dict | None = None,
) -> None:
    """Persist a single anomaly event for a bin.

    This writes to the event_log table and updates the bins.last_event_* summary
    fields so the latest anomaly is easy to query.
    """

    details_str = json.dumps(details) if details is not None else None

    insert_query = text(
        """
        INSERT INTO event_log (bin_id, event_type, details)
        VALUES (:bin_id, :event_type, :details)
        """
    )

    db.execute(
        insert_query,
        {"bin_id": bin_id, "event_type": event_type.value, "details": details_str},
    )

    update_summary_query = text(
        """
        UPDATE bins
        SET
            last_event_type = :event_type,
            last_event_at = COALESCE(:event_timestamp, NOW())
        WHERE bin_id = :bin_id
        """
    )

    db.execute(
        update_summary_query,
        {
            "bin_id": bin_id,
            "event_type": event_type.value,
            "event_timestamp": (details or {}).get("event_timestamp") if details else None,
        },
    )


def check_overflow_risk( #overflow kontrol
    db: Session,
    bin_id: str,
    new_level: FillLevelEnum,
    event_timestamp: datetime | None,
    previous_level: str | None,
) -> None:
    """Detect simple overflow risk anomalies.

    Current rule: whenever a bin transitions into CRITICAL_FULL from a
    different level, record an OVERFLOW_RISK anomaly event. If it was already
    CRITICAL_FULL, we do not spam additional events.
    """

    if new_level != FillLevelEnum.CRITICAL_FULL:
        return

    # If previous level was already CRITICAL_FULL, skip duplicate logs until
    # the bin transitions back to another state (e.g. EMPTY/FULL).
    if previous_level == FillLevelEnum.CRITICAL_FULL.value:
        return

    details: dict = {}
    if event_timestamp is not None:
        details["event_timestamp"] = event_timestamp.isoformat()

    log_anomaly_event(db, bin_id, AnomalyType.OVERFLOW_RISK, details or None)


def check_sensor_error_flag( #sensor error kontrol
    db: Session,
    bin_id: str,
    new_level: FillLevelEnum,
    event_timestamp: datetime | None,
) -> None:
    """If device explicitly reports SENSOR_ERROR, log an anomaly event.

    This is a direct mapping from the IoT enum to an anomaly record, so that
    firmware-side sensor errors are always visible in the event_log.
    """

    if new_level != FillLevelEnum.SENSOR_ERROR:
        return

    details: dict = {}
    if event_timestamp is not None:
        details["event_timestamp"] = event_timestamp.isoformat()

    # Map explicit SENSOR_ERROR from device to SENSOR_NOT_FOUND_ERROR anomaly
    log_anomaly_event(db, bin_id, AnomalyType.SENSOR_NOT_FOUND_ERROR, details or None)


def check_sensor_fixed_value_error( # sensor düzeltilmesinin kontrolü 
    db: Session,
    bin_id: str,
    window_size: int = 3,
    tolerance_cm: float = 0.2,
) -> None:
    """Detect sensor fixed-value anomalies based on raw_distance_cm history.

    Rule: if the last `window_size` telemetry samples for this bin all have
    nearly the same raw_distance_cm (within `tolerance_cm`), we assume the
    sensor is stuck and emit SENSOR_FIXED_VALUE_ERROR.
    """

    query = text(
        """
        SELECT raw_distance_cm
        FROM telemetry
        WHERE bin_id = :bin_id AND raw_distance_cm IS NOT NULL
        ORDER BY created_at DESC
        LIMIT :limit
        """
    )

    rows = db.execute(query, {"bin_id": bin_id, "limit": window_size}).mappings().all()
    if len(rows) < window_size:
        # Not enough history yet; don't flag.
        return

    distances = [row["raw_distance_cm"] for row in rows if row["raw_distance_cm"] is not None]
    if len(distances) < window_size:
        # Some missing values; be conservative.
        return

    min_val = min(distances)
    max_val = max(distances)

    if max_val - min_val <= tolerance_cm:
        details = {
            "window_size": window_size,
            "min_distance_cm": min_val,
            "max_distance_cm": max_val,
        }
        log_anomaly_event(db, bin_id, AnomalyType.SENSOR_FIXED_VALUE_ERROR, details)


def check_fill_anomaly(db: Session, bin_id: str, time_window_minutes: int = 15) -> None: #fill anomaly
    """Detect suspicious fill/empty patterns based on recent enums.

    Simple rule: if the last three enums for a bin form the pattern
    EMPTY -> CRITICAL_FULL -> EMPTY within a short time window, we
    consider this a FILL_ANOMALY (improbable fast fill and empty).
    """

    query = text(
        """
        SELECT enum_state, created_at
        FROM telemetry
        WHERE bin_id = :bin_id
        ORDER BY created_at DESC
        LIMIT 3
        """
    )

    rows = db.execute(query, {"bin_id": bin_id}).mappings().all()
    if len(rows) < 3:
        return

    # rows are ordered DESC (newest first)
    newest, mid, oldest = rows[0], rows[1], rows[2]

    if not (
        newest["enum_state"] == FillLevelEnum.EMPTY.value
        and mid["enum_state"] == FillLevelEnum.CRITICAL_FULL.value
        and oldest["enum_state"] == FillLevelEnum.EMPTY.value
    ):
        return

    # Check that the pattern happened within the allowed window
    try:
        start_time: datetime = oldest["created_at"]
        end_time: datetime = newest["created_at"]
    except Exception:
        return

    if end_time - start_time <= timedelta(minutes=time_window_minutes):
        details = {
            "start_timestamp": start_time.isoformat() if isinstance(start_time, datetime) else str(start_time),
            "end_timestamp": end_time.isoformat() if isinstance(end_time, datetime) else str(end_time),
        }
        log_anomaly_event(db, bin_id, AnomalyType.FILL_ANOMALY, details)


def fetch_recent_anomalies(db: Session, limit: int = 50) -> list[AnomalyEventOut]:
    """Return the most recent anomaly events for inspection/visualization."""

    query = text(
        """
        SELECT bin_id, event_type, details, created_at
        FROM event_log
        ORDER BY created_at DESC
        LIMIT :limit
        """
    )

    rows = db.execute(query, {"limit": limit}).mappings().all()

    events: list[AnomalyEventOut] = []
    for row in rows:
        events.append(
            AnomalyEventOut(
                bin_id=row["bin_id"],
                event_type=AnomalyType(row["event_type"]),
                details=row["details"],
                created_at=row["created_at"],
            )
        )

    return events
