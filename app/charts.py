"""Оформление графиков в тёмной теме дашборда."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# Цвета совпадают с дашбордом: тема zinc и палитра chart-1..chart-5 из shadcn/ui
BG = "#09090b"
PANEL = "#09090b"
GRID = "#27272a"
TEXT = "#fafafa"
MUTED = "#a1a1aa"
ACCENT = "#2eb88a"
ACCENT_2 = "#2662d9"
WARN = "#e88c30"
DANGER = "#ef4444"
VIOLET = "#af57db"

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
