"""
Fill history CSV analiz scripti.

Kullanım:
  python -m scripts.analyze_fill [csv_path]

CSV'yi /api/simulation/export-csv endpointinden indirin,
sonra bu scriptı calistirin.

Cikti:
  - Genel istatistikler
  - Label bazli ozet (A/B/C)
  - Dunya karsilastirmasi (algo vs fixed)
  - En cok tasma yasayan bin'ler (top 10)
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path


FIELDS = ["sim_time", "world", "bin_id", "event",
          "fill_pct", "fill_label", "distance_label", "fill_rate"]


def load_csv(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        print(f"Hata: Dosya bulunamadi -> {path}")
        sys.exit(1)
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main(csv_path: str = "fill_history.csv") -> None:
    rows = load_csv(csv_path)
    if not rows:
        print("CSV bos.")
        return

    overflows = [r for r in rows if r["event"] == "OVERFLOW"]
    emptied   = [r for r in rows if r["event"] == "EMPTIED"]

    print(f"Toplam kayit   : {len(rows)}")
    print(f"  OVERFLOW     : {len(overflows)}")
    print(f"  EMPTIED      : {len(emptied)}")

    # ── Label ozeti ────────────────────────────────────────────────────────
    label_ov  = defaultdict(int)
    label_emp = defaultdict(int)
    label_bins: dict[str, set] = defaultdict(set)

    for r in rows:
        lbl = r.get("fill_label", "?")
        label_bins[lbl].add(r["bin_id"])
        if r["event"] == "OVERFLOW":
            label_ov[lbl] += 1
        elif r["event"] == "EMPTIED":
            label_emp[lbl] += 1

    print("\n--- Label Ozeti ---")
    print(f"  {'Label':<8} {'Bin Sayisi':<12} {'Overflow':<12} {'Emptied':<10} {'OVF/Bin':<10}")
    for lbl in sorted(label_bins.keys()):
        n   = len(label_bins[lbl])
        ov  = label_ov[lbl]
        emp = label_emp[lbl]
        ratio = f"{ov/n:.1f}" if n else "-"
        print(f"  {lbl:<8} {n:<12} {ov:<12} {emp:<10} {ratio:<10}")

    # ── Dunya karsilastirmasi ───────────────────────────────────────────────
    world_ov  = defaultdict(int)
    world_emp = defaultdict(int)
    for r in rows:
        w = r.get("world", "?")
        if r["event"] == "OVERFLOW":
            world_ov[w] += 1
        elif r["event"] == "EMPTIED":
            world_emp[w] += 1

    print("\n--- Dunya Karsilastirmasi ---")
    print(f"  {'Dunya':<10} {'Overflow':<12} {'Emptied':<10}")
    for w in ("algo", "fixed"):
        print(f"  {w:<10} {world_ov[w]:<12} {world_emp[w]:<10}")

    # ── En cok tasma yasayan bin'ler ────────────────────────────────────────
    bin_ov: dict[str, int] = defaultdict(int)
    bin_info: dict[str, dict] = {}
    for r in overflows:
        bid = r["bin_id"]
        bin_ov[bid] += 1
        bin_info[bid] = {
            "label":    r.get("fill_label", "?"),
            "dist":     r.get("distance_label", "?"),
            "rate":     r.get("fill_rate", "?"),
            "world":    r.get("world", "?"),
        }

    top10 = sorted(bin_ov.items(), key=lambda x: x[1], reverse=True)[:10]
    if top10:
        print("\n--- En Cok Tasma Yasayan Bin'ler (Top 10) ---")
        print(f"  {'Bin ID':<14} {'Overflow':<10} {'Label':<8} {'Dist':<6} {'Rate/h':<10} {'World'}")
        for bid, cnt in top10:
            info = bin_info[bid]
            print(f"  {bid:<14} {cnt:<10} {info['label']:<8} {info['dist']:<6} {info['rate']:<10} {info['world']}")

    print("\nAnaliz tamamlandi.")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "fill_history.csv"
    main(path)
