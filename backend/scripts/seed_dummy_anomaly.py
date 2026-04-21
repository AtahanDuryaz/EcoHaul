from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / "backend" / ".env")
load_dotenv(ROOT_DIR / "backend" / ".env.example")


def get_database_url() -> str:
    from os import getenv

    url = getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not defined in backend/.env or backend/.env.example")
    return url


def main() -> None:
    database_url = get_database_url()
    engine = create_engine(database_url, pool_pre_ping=True)

    with engine.begin() as connection:
        # Pick an existing bin_id; adjust if needed
        bin_id = "WMS1873"
        insert_query = text(
            """
            INSERT INTO event_log (bin_id, event_type, details)
            VALUES (:bin_id, :event_type, :details)
            """
        )
        connection.execute(
            insert_query,
            {
                "bin_id": bin_id,
                "event_type": "OVERFLOW_RISK",
                "details": "Dummy anomaly event for UI testing",
            },
        )

        update_bins = text(
            """
            UPDATE bins
            SET last_event_type = :event_type, last_event_at = NOW()
            WHERE bin_id = :bin_id
            """
        )
        connection.execute(update_bins, {"bin_id": bin_id, "event_type": "OVERFLOW_RISK"})

    print("Seeded dummy anomaly for bin", bin_id)


if __name__ == "__main__":
    main()
