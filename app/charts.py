"""Оформление графиков в тёмной теме дашборда."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

BG = "#0e1116"
PANEL = "#151a21"
GRID = "#242b35"
TEXT = "#e6e9ee"
MUTED = "#8b949e"
ACCENT = "#4ade80"
ACCENT_2 = "#38bdf8"
WARN = "#fbbf24"
DANGER = "#f87171"
VIOLET = "#a78bfa"

PALETTE = [ACCENT, ACCENT_2, VIOLET, WARN, DANGER, "#f472b6"]

CHARTS_DIR = Path(__file__).resolve().parent.parent / "reports" / "charts"


def apply_style() -> None:
    plt.rcParams.update({
        "figure.facecolor": BG,
        "axes.facecolor": PANEL,
        "savefig.facecolor": BG,
        "axes.edgecolor": GRID,
        "axes.labelcolor": TEXT,
        "axes.titlecolor": TEXT,
        "text.color": TEXT,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "grid.color": GRID,
        "grid.linestyle": "-",
        "grid.linewidth": 0.7,
        "axes.grid": True,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "font.size": 10,
        "figure.dpi": 130,
        "legend.frameon": False,
    })


def new_figure(width: float = 8.0, height: float = 4.2):
    apply_style()
    fig, ax = plt.subplots(figsize=(width, height))
    return fig, ax


def save(fig, name: str) -> Path:
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    path = CHARTS_DIR / name
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path
