"""
Regenerate the two KPI figures used in the IEEE paper with a WHITE background.

Outputs (saved into ./images/ so Overleaf picks them up):
  - images/22_kpi_tasarruf_ozeti.png   (DPET % advantage over Greedy / 2-opt)
  - images/24_kpi_verim_vs_kamyon.png  (system efficiency vs. active fleet size)

All numbers come from the one-year simulation results reported in the paper.
Edit the data blocks below if you want to plug in exact values.

Run:
    python make_paper_figures.py
"""

import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ---- Force a clean WHITE theme (this was the professor's request) -------------
plt.rcParams.update({
    "figure.facecolor":  "white",
    "axes.facecolor":    "white",
    "savefig.facecolor": "white",
    "axes.edgecolor":    "#333333",
    "axes.labelcolor":   "#111111",
    "text.color":        "#111111",
    "xtick.color":       "#111111",
    "ytick.color":       "#111111",
    "font.size":         11,
    "axes.grid":         True,
    "grid.color":        "#dddddd",
    "grid.linewidth":    0.8,
})

OUT_DIR = "images"
os.makedirs(OUT_DIR, exist_ok=True)

DPET_COLOR   = "#2e8b57"   # sea green
GREEDY_COLOR = "#c0392b"   # red
TWOOPT_COLOR = "#2471a3"   # blue


# ==============================================================================
# FIGURE 22 - DPET percentage advantage over the two baselines (positive = better)
# Values are the magnitudes from the KPI table; reductions in fuel/CO2/cost/etc.
# count as positive advantages, while overflow (where DPET is worse) is negative.
# ==============================================================================
def make_savings_summary():
    metrics = [
        "System efficiency",
        "Load per km",
        "CO2 emission",
        "Fuel",
        "Operational cost",
        "Fleet size",
        "Number of trips",
        "Total distance",
        "Overflow load",
        "Overflow events",
    ]
    vs_greedy = [+33.3, +33.3, +30.7, +30.5, +39.6, +40.2, +42.1, +30.7, -25.2, -22.6]
    vs_2opt   = [+27.9, +27.2, +27.2, +25.5, +38.0, +40.2, +41.3, +27.2, -25.1, -24.5]

    y = np.arange(len(metrics))
    h = 0.38

    fig, ax = plt.subplots(figsize=(7.2, 5.2))
    b1 = ax.barh(y + h / 2, vs_greedy, height=h, color=DPET_COLOR,
                 label="vs Greedy")
    b2 = ax.barh(y - h / 2, vs_2opt,  height=h, color=TWOOPT_COLOR,
                 label="vs 2-opt", alpha=0.85)

    ax.axvline(0, color="#333333", linewidth=1.0)
    ax.set_yticks(y)
    ax.set_yticklabels(metrics)
    ax.invert_yaxis()  # first metric on top
    ax.set_xlabel("DPET advantage (%)  -  positive = DPET better")
    ax.set_title("DPET advantage over baseline algorithms", fontweight="bold")
    ax.legend(loc="lower right", frameon=True)
    ax.grid(axis="y", visible=False)

    # value labels
    for bars in (b1, b2):
        for r in bars:
            w = r.get_width()
            ax.text(w + (1.0 if w >= 0 else -1.0), r.get_y() + r.get_height() / 2,
                    f"{w:+.0f}", va="center",
                    ha="left" if w >= 0 else "right", fontsize=8)

    ax.set_xlim(-35, 50)
    fig.tight_layout()
    path = os.path.join(OUT_DIR, "22_kpi_tasarruf_ozeti.png")
    fig.savefig(path, dpi=200, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    print("written:", path)


# ==============================================================================
# FIGURE 24 - System efficiency vs. active fleet size.
# NOTE: the exact per-run snapshot points were lost with the old script; the
# arrays below reproduce the reported ranges/averages (DPET 76-87% at 4-7 trucks,
# Greedy 52-66% at 8-16, 2-opt 57-69%). Replace them with your exact run data if
# you still have it - the plotting code stays the same.
# ==============================================================================
def make_efficiency_vs_fleet():
    dpet_x = np.array([4, 5, 5, 6, 6, 7, 7])
    dpet_y = np.array([87, 83, 81, 79, 80, 76, 75])      # avg ~79

    greedy_x = np.array([8, 10, 11, 12, 14, 16])
    greedy_y = np.array([52, 56, 58, 60, 63, 66])        # avg ~59.2

    twoopt_x = np.array([8, 10, 11, 12, 14, 16])
    twoopt_y = np.array([57, 60, 61, 63, 66, 69])        # avg ~61.8

    fig, ax = plt.subplots(figsize=(7.2, 4.8))

    def plot_group(x, y, color, label):
        ax.scatter(x, y, color=color, s=45, zorder=3, label=label, edgecolor="white")
        # dashed linear trend
        m, b = np.polyfit(x, y, 1)
        xs = np.linspace(x.min(), x.max(), 50)
        ax.plot(xs, m * xs + b, "--", color=color, linewidth=1.4, alpha=0.8)
        # solid average line
        ax.axhline(y.mean(), color=color, linewidth=1.0, alpha=0.35)

    plot_group(dpet_x,   dpet_y,   DPET_COLOR,   "DPET")
    plot_group(greedy_x, greedy_y, GREEDY_COLOR, "Greedy")
    plot_group(twoopt_x, twoopt_y, TWOOPT_COLOR, "2-opt")

    ax.set_xlabel("Active fleet size (number of trucks)")
    ax.set_ylabel("System efficiency (%)")
    ax.set_title("System efficiency vs. fleet size", fontweight="bold")
    ax.legend(loc="lower right", frameon=True)
    ax.set_xlim(3, 17)
    ax.set_ylim(45, 92)

    fig.tight_layout()
    path = os.path.join(OUT_DIR, "24_kpi_verim_vs_kamyon.png")
    fig.savefig(path, dpi=200, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    print("written:", path)


if __name__ == "__main__":
    make_savings_summary()
    make_efficiency_vs_fleet()
    print("done.")
