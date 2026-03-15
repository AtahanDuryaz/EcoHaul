from __future__ import annotations

import csv
import json
import re
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
SOURCE_FILE = ROOT_DIR / "dataset" / "dcc_public_bin_locations.csv"
OUTPUT_FILE = ROOT_DIR / "backend" / "data" / "clean_bins.csv"
REPORT_FILE = ROOT_DIR / "backend" / "data" / "cleaning_report.json"

BIN_ID_PATTERN = re.compile(r"^WMS\d{4,5}$")
AMBIGUOUS_MAP = str.maketrans({"O": "0", "I": "1", "L": "1", "S": "5", "B": "8", "E": "8"})


def normalize_bin_id(raw_value: str) -> str:
    value = (raw_value or "").strip().upper().replace(" ", "")
    if not value.startswith("WMS"):
        return value

    prefix = "WMS"
    suffix = value[3:].translate(AMBIGUOUS_MAP)
    suffix = "".join(char for char in suffix if char.isalnum())
    return f"{prefix}{suffix}"


def parse_coordinate(raw_value: str) -> float | None:
    try:
        return float((raw_value or "").strip())
    except ValueError:
        return None


def main() -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    seen_bin_ids: set[str] = set()
    cleaned_rows: list[dict] = []

    stats = {
        "source_rows": 0,
        "kept_rows": 0,
        "dropped_empty_bin_id": 0,
        "dropped_invalid_bin_id": 0,
        "dropped_duplicate_bin_id": 0,
        "dropped_invalid_coordinates": 0,
    }

    with SOURCE_FILE.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        for row in reader:
            stats["source_rows"] += 1

            normalized_bin_id = normalize_bin_id(row.get("Bin_ID", ""))
            if not normalized_bin_id:
                stats["dropped_empty_bin_id"] += 1
                continue

            if not BIN_ID_PATTERN.match(normalized_bin_id):
                stats["dropped_invalid_bin_id"] += 1
                continue

            if normalized_bin_id in seen_bin_ids:
                stats["dropped_duplicate_bin_id"] += 1
                continue

            irish_x = parse_coordinate(row.get("Irish_X", ""))
            irish_y = parse_coordinate(row.get("Irish_Y", ""))
            if irish_x is None or irish_y is None:
                stats["dropped_invalid_coordinates"] += 1
                continue

            cleaned_rows.append(
                {
                    "bin_id": normalized_bin_id,
                    "region": (row.get("ELectoral_Area", "") or "").strip(),
                    "bin_type": (row.get("Bin_Type", "") or "").strip(),
                    "irish_x": irish_x,
                    "irish_y": irish_y,
                }
            )
            seen_bin_ids.add(normalized_bin_id)

    stats["kept_rows"] = len(cleaned_rows)

    with OUTPUT_FILE.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=["bin_id", "region", "bin_type", "irish_x", "irish_y"],
        )
        writer.writeheader()
        writer.writerows(cleaned_rows)

    with REPORT_FILE.open("w", encoding="utf-8") as report:
        json.dump(stats, report, indent=2)

    print(json.dumps(stats, indent=2))
    print(f"Clean file: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
