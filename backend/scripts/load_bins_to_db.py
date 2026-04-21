from __future__ import annotations

from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

ROOT_DIR = Path(__file__).resolve().parents[2]
INPUT_FILE = ROOT_DIR / "backend" / "data" / "bins_wgs84.csv"
INIT_SQL_FILE = ROOT_DIR / "backend" / "database" / "init.sql"

load_dotenv(ROOT_DIR / "backend" / ".env")
load_dotenv(ROOT_DIR / "backend" / ".env.example")



def get_database_url() -> str:
    from os import getenv

    url = getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not defined in backend/.env or backend/.env.example")
    return url


def main() -> None:
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Input file not found: {INPUT_FILE}")

    database_url = get_database_url()
    engine = create_engine(database_url, pool_pre_ping=True)

    dataframe = pd.read_csv(INPUT_FILE)
    records = dataframe.to_dict(orient="records")

    with engine.begin() as connection:
        init_sql = INIT_SQL_FILE.read_text(encoding="utf-8")
        connection.execute(text(init_sql))

        # Initialize new IoT-related columns with sensible defaults for imported data
        for record in records:
            # Ensure last_emptied_at is either a proper timestamp or NULL, not NaN/double
            if "last_emptied_at" in record and pd.isna(record["last_emptied_at"]):
                record["last_emptied_at"] = None

            record.setdefault("fill_level", None)
            record.setdefault("is_active", True)
            record.setdefault("last_seen_at", None)
            record.setdefault("last_enum_transition", None)
            record.setdefault("last_enum_change_at", None)

        upsert_query = text(
            """
            INSERT INTO bins (
                bin_id,
                latitude,
                longitude,
                status,
                region,
                last_emptied_at,
                fill_level,
                is_active,
                last_seen_at,
                last_enum_transition,
                last_enum_change_at,
                geom
            ) VALUES (
                :bin_id,
                :latitude,
                :longitude,
                :status,
                :region,
                :last_emptied_at,
                :fill_level,
                :is_active,
                :last_seen_at,
                :last_enum_transition,
                :last_enum_change_at,
                ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography
            )
            ON CONFLICT (bin_id) DO UPDATE SET
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude,
                status = EXCLUDED.status,
                region = EXCLUDED.region,
                last_emptied_at = EXCLUDED.last_emptied_at,
                fill_level = EXCLUDED.fill_level,
                is_active = EXCLUDED.is_active,
                last_seen_at = EXCLUDED.last_seen_at,
                last_enum_transition = EXCLUDED.last_enum_transition,
                last_enum_change_at = EXCLUDED.last_enum_change_at,
                geom = EXCLUDED.geom
            """
        )

        connection.execute(upsert_query, records)

    print(f"Loaded bins: {len(records)}")


if __name__ == "__main__":
    main()
