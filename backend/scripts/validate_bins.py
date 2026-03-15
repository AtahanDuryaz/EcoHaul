from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]
INPUT_FILE = ROOT_DIR / "backend" / "data" / "bins_wgs84.csv"
REPORT_FILE = ROOT_DIR / "backend" / "data" / "bins_validation_report.json"

LAT_MIN = 53.20
LAT_MAX = 53.45
LON_MIN = -6.45
LON_MAX = -6.05


def main() -> None:
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"WGS84 file not found: {INPUT_FILE}")

    dataframe = pd.read_csv(INPUT_FILE)

    valid_mask = (
        dataframe["latitude"].between(LAT_MIN, LAT_MAX)
        & dataframe["longitude"].between(LON_MIN, LON_MAX)
    )

    invalid_rows = dataframe.loc[~valid_mask, ["bin_id", "latitude", "longitude"]]

    report = {
        "total_records": int(len(dataframe)),
        "valid_in_dublin": int(valid_mask.sum()),
        "invalid": int((~valid_mask).sum()),
        "bounds": {
            "lat_min": LAT_MIN,
            "lat_max": LAT_MAX,
            "lon_min": LON_MIN,
            "lon_max": LON_MAX,
        },
        "invalid_samples": invalid_rows.head(20).to_dict(orient="records"),
    }

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_FILE.open("w", encoding="utf-8") as report_file:
        json.dump(report, report_file, indent=2)

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
