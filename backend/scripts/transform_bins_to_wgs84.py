from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]
INPUT_FILE = ROOT_DIR / "backend" / "data" / "clean_bins.csv"
OUTPUT_FILE = ROOT_DIR / "backend" / "data" / "bins_wgs84.csv"
REPORT_FILE = ROOT_DIR / "backend" / "data" / "transform_report.json"

LAT_MIN = 53.20
LAT_MAX = 53.45
LON_MIN = -6.45
LON_MAX = -6.05

SOURCE_CRS_CANDIDATES = ["EPSG:2157", "EPSG:29903", "EPSG:29902"]


def score_dublin_fit(frame: gpd.GeoDataFrame) -> int:
    latitudes = frame.geometry.y
    longitudes = frame.geometry.x
    in_bbox = latitudes.between(LAT_MIN, LAT_MAX) & longitudes.between(LON_MIN, LON_MAX)
    return int(in_bbox.sum())


def convert_with_best_crs(dataframe: pd.DataFrame) -> tuple[gpd.GeoDataFrame, str]:
    best_crs = SOURCE_CRS_CANDIDATES[0]
    best_score = -1
    best_frame: gpd.GeoDataFrame | None = None

    for source_crs in SOURCE_CRS_CANDIDATES:
        geodataframe = gpd.GeoDataFrame(
            dataframe,
            geometry=gpd.points_from_xy(dataframe["irish_x"], dataframe["irish_y"]),
            crs=source_crs,
        ).to_crs("EPSG:4326")

        score = score_dublin_fit(geodataframe)
        if score > best_score:
            best_score = score
            best_crs = source_crs
            best_frame = geodataframe

    if best_frame is None:
        raise RuntimeError("CRS transformation failed for all candidates")

    return best_frame, best_crs


def main() -> None:
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Clean file not found: {INPUT_FILE}")

    dataframe = pd.read_csv(INPUT_FILE)

    geodataframe, selected_source_crs = convert_with_best_crs(dataframe)

    geodataframe["latitude"] = geodataframe.geometry.y.round(7)
    geodataframe["longitude"] = geodataframe.geometry.x.round(7)
    geodataframe["status"] = "OFFLINE"
    geodataframe["last_emptied_at"] = pd.NA

    output = geodataframe[
        ["bin_id", "region", "bin_type", "latitude", "longitude", "status", "last_emptied_at"]
    ]

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(OUTPUT_FILE, index=False)

    report = {
        "total_records": int(len(output)),
        "selected_source_crs": selected_source_crs,
        "output_file": str(OUTPUT_FILE),
        "latitude_min": float(output["latitude"].min()),
        "latitude_max": float(output["latitude"].max()),
        "longitude_min": float(output["longitude"].min()),
        "longitude_max": float(output["longitude"].max()),
    }

    with REPORT_FILE.open("w", encoding="utf-8") as report_file:
        json.dump(report, report_file, indent=2)

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
