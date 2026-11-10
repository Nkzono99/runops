"""Make the example figures and table.

The example uses a synthetic temperature field so that it runs without simulation
output. In a real investigation this script reads the runs listed in the README.

Usage (from the investigation directory): python scripts/make_figures.py
"""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

OUT = Path(__file__).resolve().parents[1] / "out"
AMBIENT = 20.0  # plate temperature with the heater off [degC]
PEAK = 30.0  # temperature rise at the heater centre [K]
DECAY = 6.0  # decay length of the rise [cm]
RING = 3.0  # radius of the ring that represents the sensor's surroundings [cm]
OFFSETS = (0.0, 2.0, 4.0, 8.0, 12.0)  # heater distance from the sensor [cm]
SHOWN = (0.0, 8.0)  # offsets shown as maps in figure 1
HALF_WIDTH = 15.0  # half width of the plotted region [cm]


def temperature(x: np.ndarray, y: np.ndarray, offset: float | None) -> np.ndarray:
    """Plate temperature with the sensor at the origin and the heater at (offset, 0)."""
    if offset is None:
        return np.full(np.shape(x), AMBIENT)
    return AMBIENT + PEAK * np.exp(-np.hypot(x - offset, y) / DECAY)


def sensor_and_ring(offset: float | None) -> tuple[float, float]:
    """Temperature at the sensor and its mean over the ring around the sensor."""
    angle = np.linspace(0.0, 2.0 * np.pi, 720, endpoint=False)
    ring = temperature(RING * np.cos(angle), RING * np.sin(angle), offset)
    sensor = temperature(np.zeros(1), np.zeros(1), offset)
    return float(sensor[0]), float(ring.mean())


def figure_maps() -> None:
    axis = np.linspace(-HALF_WIDTH, HALF_WIDTH, 301)
    x, y = np.meshgrid(axis, axis)
    cases: list[tuple[str, float | None]] = [
        ("Heater off", None),
        ("Heater at the sensor", SHOWN[0]),
        (f"Heater {SHOWN[1]:.0f} cm away", SHOWN[1]),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(9.0, 3.3), sharey=True, constrained_layout=True)
    for ax, (label, offset) in zip(axes, cases, strict=True):
        image = ax.imshow(
            temperature(x, y, offset),
            extent=(-HALF_WIDTH, HALF_WIDTH, -HALF_WIDTH, HALF_WIDTH),
            origin="lower",
            cmap="inferno",
            vmin=AMBIENT,
            vmax=AMBIENT + PEAK,
        )
        ax.add_patch(plt.Circle((0.0, 0.0), RING, fill=False, color="white", ls="--", lw=1.0))
        ax.plot(0.0, 0.0, "o", mfc="none", mec="white", ms=7, mew=1.5)
        if offset is not None:
            ax.plot(offset, 0.0, "^", color="cyan", ms=7)
        sensor, _ = sensor_and_ring(offset)
        ax.set_title(f"{label}\nsensor {sensor:.1f} °C", fontsize=10)
        ax.set_xlabel("x [cm]")
    axes[0].set_ylabel("y [cm]")
    fig.colorbar(image, ax=axes, label="temperature [°C]", shrink=0.9)
    fig.savefig(OUT / "fig1_maps.png", dpi=90)
    plt.close(fig)


def figure_dependence(rows: list[dict[str, float]]) -> None:
    offsets = [row["offset_cm"] for row in rows]
    panels = [
        ("rise_K", "sensor rise over heater off [K]"),
        ("sensor_minus_ring_K", "sensor minus surroundings [K]"),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(8.0, 3.1), constrained_layout=True)
    for ax, (key, label) in zip(axes, panels, strict=True):
        values = [row[key] for row in rows]
        ax.plot(offsets, values, "o-", color="0.3", mfc="white")
        for row in rows:
            if row["offset_cm"] in SHOWN:
                ax.plot(row["offset_cm"], row[key], "o", color="tab:red")
        ax.axhline(0.0, color="0.6", lw=0.8)
        ax.set_xlabel("heater distance from the sensor [cm]")
        ax.set_ylabel(label)
    axes[0].set_title("(a) how much the sensor warms", fontsize=10)
    axes[1].set_title("(b) hot spot at the sensor", fontsize=10)
    fig.savefig(OUT / "fig2_dependence.png", dpi=90)
    plt.close(fig)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    base, _ = sensor_and_ring(None)
    rows = []
    for offset in OFFSETS:
        sensor, ring = sensor_and_ring(offset)
        rows.append(
            {
                "offset_cm": offset,
                "sensor_degC": round(sensor, 2),
                "rise_K": round(sensor - base, 2),
                "ring_mean_degC": round(ring, 2),
                "sensor_minus_ring_K": round(sensor - ring, 2),
            }
        )
    with (OUT / "values.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    figure_maps()
    figure_dependence(rows)


if __name__ == "__main__":
    main()
