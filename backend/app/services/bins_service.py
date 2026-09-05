import csv
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..schemas import FillLevelEnum, HeartbeatIn, StateChangeIn
from .anomaly_service import (
    check_fill_anomaly,
    check_overflow_risk,
    check_sensor_error_flag,
    check_sensor_fixed_value_error,
)

ROOT_DIR = Path(__file__).resolve().parents[3]
FALLBACK_CSV = ROOT_DIR / "backend" / "data" / "bins_wgs84.csv"


def _load_bins_from_csv() -> list[dict]: #csv den schemaya uygun olarak bin locationları listeye aktarılıyor
    if not FALLBACK_CSV.exists():
        return []

    bins: list[dict] = []
    with FALLBACK_CSV.open("r", encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            bins.append(
                {
                    "bin_id": row["bin_id"],
                    "lat": float(row["latitude"]),
                    "lon": float(row["longitude"]),
                    "status": row.get("status", "OFFLINE") or "OFFLINE",
                    "region": row.get("region", "Unknown") or "Unknown",
                    "last_emptied_at": None,
                }
            )

    return bins


def fetch_bins(db: Session) -> list[dict]: #bu binlerin bilgilerinin görülmesi için query oluşturulması
    query = text(
        """
        SELECT
            bin_id,
            latitude AS lat,
            longitude AS lon,
            status,
            region,
            last_emptied_at,
            fill_level,
            is_active,
            last_seen_at,
            last_enum_transition,
            last_enum_change_at
        FROM bins
        ORDER BY bin_id
        """
    )

    try:
        rows = db.execute(query).mappings().all()
        return [dict(row) for row in rows]
    except SQLAlchemyError:
        return _load_bins_from_csv()


def fetch_summary(db: Session) -> dict:
    try:
        total_bins = db.execute(text("SELECT COUNT(*) FROM bins")).scalar_one()
        offline_bins = db.execute(
            text("SELECT COUNT(*) FROM bins WHERE status = 'OFFLINE'")
        ).scalar_one()

        region_rows = db.execute(
            text(
                """
                SELECT region, COUNT(*) AS count
                FROM bins
                GROUP BY region
                ORDER BY region
                """
            )
        ).mappings().all()

        regions = {row["region"]: row["count"] for row in region_rows}
        return {
            "total_bins": total_bins,
            "offline_bins": offline_bins,
            "regions": regions,
        }
    except SQLAlchemyError:
        bins = _load_bins_from_csv()
        regions: dict[str, int] = {}
        for item in bins:
            region = item["region"]
            regions[region] = regions.get(region, 0) + 1

        return {
            "total_bins": len(bins),
            "offline_bins": sum(1 for item in bins if item["status"] == "OFFLINE"),
            "regions": regions,
        }


def log_state_change(db: Session, bin_id: str, payload: StateChangeIn) -> None: #sensör versini işleyen ana fonksiyon
    """Insert telemetry row and update bin's IoT-related fields.

    - Inserts a telemetry event with enum_state and optional raw distance.
    - Updates bins.fill_level, is_active, last_seen_at and last enum change info.
    """

    telemetry_query = text( #telemetry 
        """
        INSERT INTO telemetry (bin_id, enum_state, raw_distance_cm)
        VALUES (:bin_id, :enum_state, :raw_distance_cm)
        """
    )

    db.execute(
        telemetry_query,
        {
            "bin_id": bin_id,
            "enum_state": payload.enum_state.value,
            "raw_distance_cm": payload.median_distance_cm,
        },
    )

    # Capture previous fill_level before updating, if needed for future rules
    previous_level_query = text(
        """
        SELECT fill_level
        FROM bins
        WHERE bin_id = :bin_id
        """
    )

    previous_level_value = db.execute(
        previous_level_query, {"bin_id": bin_id}
    ).scalar_one_or_none()

    # Update current bin status and last enum transition summary
    update_query = text( #bins update oluyor
        """
        UPDATE bins
        SET
            last_enum_transition = CASE
                WHEN fill_level IS NULL OR fill_level = :new_fill_level THEN last_enum_transition
                ELSE fill_level || '->' || :new_fill_level
            END,
            last_enum_change_at = CASE
                WHEN fill_level IS NULL OR fill_level = :new_fill_level THEN last_enum_change_at
                ELSE COALESCE(:event_timestamp, NOW())
            END,
            fill_level = :new_fill_level,
            is_active = TRUE,
            last_seen_at = COALESCE(:event_timestamp, NOW()),
            status = CASE
                WHEN :new_fill_level = 'CRITICAL_FULL' THEN 'CRITICAL_FULL'
                WHEN :new_fill_level = 'FULL' THEN 'FULL'
                WHEN :new_fill_level = 'EMPTY' THEN 'EMPTY'
                ELSE status
            END
        WHERE bin_id = :bin_id
        """
    )

    db.execute(
        update_query,
        {
            "bin_id": bin_id,
            "new_fill_level": payload.enum_state.value,
            "event_timestamp": payload.event_timestamp,
        },
    )

    # Run simple anomaly checks based on the new measurement and fill level
    try:
        new_level_enum = payload.enum_state
        # CRITICAL_FULL -> OVERFLOW_RISK
        check_overflow_risk( #kritik durumu geçti mi kontrolü
            db,
            bin_id,
            new_level_enum,
            payload.event_timestamp,
            previous_level_value,
        )
        # Device reported SENSOR_ERROR explicitly
        check_sensor_error_flag(db, bin_id, new_level_enum, payload.event_timestamp)
        # Fixed sensor value over recent samples
        check_sensor_fixed_value_error(db, bin_id)
        # Suspicious fast EMPTY/FULL/EMPTY pattern
        check_fill_anomaly(db, bin_id)
    except Exception:
        # Anomaly detection must not break state-change handling
        pass

    # Persist telemetry insert, bin update and any anomaly events
    db.commit() #bunla commit

    # Live simulation engine'e enjekte et — DB kalıcılığından bağımsız, hatası
    # state-change akışını bozmamalı.
    try:
        from ..simulation_engine import engine
        engine.inject_sensor_reading(
            bin_id=bin_id,
            enum_state=payload.enum_state.value,
            median_distance_cm=payload.median_distance_cm,
        )
    except Exception:
        pass


def log_heartbeat(db: Session, bin_id: str, payload: HeartbeatIn) -> None:
    """Update is_active/last_seen_at on heartbeat, optionally fill_level.

    Does NOT touch last_enum_transition / last_enum_change_at.
    """

    update_query = text(
        """
        UPDATE bins
        SET
            is_active = TRUE,
            last_seen_at = NOW(),
            fill_level = COALESCE(:fill_level, fill_level)
        WHERE bin_id = :bin_id
        """
    )

    db.execute(
        update_query,
        {
            "bin_id": bin_id,
            "fill_level": payload.current_enum.value if payload.current_enum else None,
        },
    )

    # Persist heartbeat update
    db.commit()
