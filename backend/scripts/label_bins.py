"""
Add distance_label and fill_label columns to bins table and populate them.

distance_label : 1 = yakın (<3 km depot), 2 = orta (3-8 km), 3 = uzak (>=8 km)
fill_label     : A = hızlı dolum (~8 sa), B = orta (~25 sa), C = yavaş (~83 sa)
                 İlk %22 bin → A, sonraki %18 → B, kalan %60 → C
                 (sıralama: bin_id alfabetik)
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.database import SessionLocal
from sqlalchemy import text

DEPOT_LAT, DEPOT_LON = 53.3498, -6.2603


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def get_distance_label(km: float) -> int:
    if km < 3.0:
        return 1
    if km < 8.0:
        return 2
    return 3


def main() -> None:
    db = SessionLocal()
    try:
        # 1. Kolonları ekle (idempotent)
        db.execute(text("""
            ALTER TABLE bins
            ADD COLUMN IF NOT EXISTS distance_label INTEGER,
            ADD COLUMN IF NOT EXISTS fill_label VARCHAR(1)
        """))
        db.commit()
        print("Kolonlar hazır.")

        # 2. Tüm bin'leri çek
        rows = db.execute(text(
            "SELECT bin_id, latitude, longitude FROM bins ORDER BY bin_id"
        )).mappings().all()

        total = len(rows)
        print(f"Toplam {total} bin bulundu.")

        # 3. Fill label eşikleri (indeks bazlı)
        a_end = int(total * 0.22)
        b_end = int(total * 0.40)

        updates = []
        for idx, row in enumerate(rows):
            km = haversine_km(DEPOT_LAT, DEPOT_LON, row["latitude"], row["longitude"])
            d_label = get_distance_label(km)
            f_label = "A" if idx < a_end else ("B" if idx < b_end else "C")
            updates.append({
                "bin_id": row["bin_id"],
                "distance_label": d_label,
                "fill_label": f_label,
            })

        # 4. Toplu güncelle
        db.execute(text("""
            UPDATE bins
            SET distance_label = :distance_label,
                fill_label      = :fill_label
            WHERE bin_id = :bin_id
        """), updates)
        db.commit()

        counts = {"A": 0, "B": 0, "C": 0}
        dist_counts = {1: 0, 2: 0, 3: 0}
        for u in updates:
            counts[u["fill_label"]] += 1
            dist_counts[u["distance_label"]] += 1

        print(f"Fill label  : A={counts['A']}  B={counts['B']}  C={counts['C']}")
        print(f"Dist label  : 1(yakin)={dist_counts[1]}  2(orta)={dist_counts[2]}  3(uzak)={dist_counts[3]}")
        print("Etiketleme tamamlandi.")

    finally:
        db.close()


if __name__ == "__main__":
    main()
