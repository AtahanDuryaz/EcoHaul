import csv
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

ROOT_DIR = Path(__file__).resolve().parents[3]
FALLBACK_CSV = ROOT_DIR / "backend" / "data" / "bins_wgs84.csv"


def _load_bins_from_csv() -> list[dict]:
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


def fetch_bins(db: Session) -> list[dict]:
    query = text(
        """
        SELECT
            bin_id,
            latitude AS lat,
            longitude AS lon,
            status,
            region,
            last_emptied_at
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
