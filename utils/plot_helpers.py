from __future__ import annotations

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence, Tuple, Union


def _save_figure(fig: Figure, filename: Union[str, Path]) -> None:
    filename = Path(filename)
    filename.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(filename), bbox_inches="tight")


def plot_3d_paths(
    paths: Sequence[Sequence[Sequence[float]]],
    labels: Sequence[str],
    colors: Optional[Sequence[str]] = None,
    linestyles: Optional[Sequence[str]] = None,
    linewidths: Optional[Sequence[float]] = None,
    title: Optional[str] = None,
    xlabel: str = "x",
    ylabel: str = "y",
    zlabel: str = "z",
    save: bool = False,
    filename: Optional[Union[str, Path]] = None,
    show: bool = True,
    figsize: Tuple[float, float] = (10.0, 8.0),
) -> Tuple[Figure, Any]:
    """Plot multiple 3D trajectories on the same axes."""
    fig = plt.figure(figsize=figsize)
    ax = fig.add_subplot(111, projection="3d")

    for idx, path in enumerate(paths):
        array = np.asarray(path, dtype=float)
        if array.ndim != 2 or array.shape[1] != 3:
            raise ValueError("Each path must be shape (N, 3) for x, y, z coordinates.")

        label = labels[idx] if idx < len(labels) else None
        color = colors[idx] if colors is not None and idx < len(colors) else None
        linestyle = linestyles[idx] if linestyles is not None and idx < len(linestyles) else "-"
        linewidth = linewidths[idx] if linewidths is not None and idx < len(linewidths) else 1.5

        ax.plot(
            array[:, 0],
            array[:, 1],
            array[:, 2],
            label=label,
            color=color,
            linestyle=linestyle,
            linewidth=linewidth,
        )

    ax.set_title(title if title is not None else "3D Trajectories")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_zlabel(zlabel)
    ax.grid(True, linestyle="--", alpha=0.4)
    if labels:
        ax.legend()

    if save and filename is not None:
        _save_figure(fig, filename)
    if show:
        plt.show()
    else:
        plt.close(fig)

    return fig, ax


def plot_2d_series(
    x_series: Union[Sequence[float], Sequence[Sequence[float]]],
    y_series: Sequence[Sequence[float]],
    labels: Sequence[str],
    colors: Optional[Sequence[str]] = None,
    linestyles: Optional[Sequence[str]] = None,
    markers: Optional[Sequence[str]] = None,
    title: Optional[str] = None,
    xlabel: str = "x",
    ylabel: str = "y",
    save: bool = False,
    filename: Optional[Union[str, Path]] = None,
    show: bool = True,
    figsize: Tuple[float, float] = (10.0, 6.0),
) -> Tuple[Figure, Any]:
    """Plot multiple 2D series on a single axes."""
    if len(y_series) == 0:
        raise ValueError("At least one y series must be provided.")

    if isinstance(x_series[0], (list, tuple, np.ndarray)):
        x_iter = [np.asarray(x, dtype=float) for x in x_series]
        if len(x_iter) != len(y_series):
            raise ValueError("x_series and y_series must have the same number of series.")
    else:
        x_array = np.asarray(x_series, dtype=float)
        x_iter = [x_array for _ in y_series]

    fig, ax = plt.subplots(figsize=figsize)
    for idx, y in enumerate(y_series):
        y_array = np.asarray(y, dtype=float)
        x_array = x_iter[idx]
        if x_array.shape != y_array.shape:
            raise ValueError("Each x/y series pair must have the same shape.")

        kwargs = {
            "label": labels[idx] if idx < len(labels) else None,
            "color": colors[idx] if colors is not None and idx < len(colors) else None,
            "linestyle": linestyles[idx] if linestyles is not None and idx < len(linestyles) else "-",
            "marker": markers[idx] if markers is not None and idx < len(markers) else None,
            "alpha": 0.85,
        }
        ax.plot(x_array, y_array, **{k: v for k, v in kwargs.items() if v is not None})

    ax.set_title(title if title is not None else "2D Series")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, linestyle="--", alpha=0.4)
    if labels:
        ax.legend()

    if save and filename is not None:
        _save_figure(fig, filename)
    if show:
        plt.show()
    else:
        plt.close(fig)

    return fig, ax


def plot_grouped_histogram(
    categories: Sequence[str],
    counts: Sequence[Sequence[float]],
    labels: Sequence[str],
    colors: Optional[Sequence[str]] = None,
    title: Optional[str] = None,
    xlabel: str = "Range",
    ylabel: str = "Count",
    save: bool = False,
    filename: Optional[Union[str, Path]] = None,
    show: bool = True,
    figsize: Tuple[float, float] = (10.0, 6.0),
    bar_alpha: float = 0.85,
) -> Tuple[Figure, Any]:
    """Plot grouped histograms for one category per bar group."""
    counts_array = np.asarray(counts, dtype=float)
    if counts_array.ndim != 2:
        raise ValueError("counts must be a 2D sequence of shape (series, categories).")
    if counts_array.shape[1] != len(categories):
        raise ValueError("Each count series must have the same length as categories.")
    if counts_array.shape[0] != len(labels):
        raise ValueError("There must be one label per count series.")

    fig, ax = plt.subplots(figsize=figsize)
    indices = np.arange(len(categories))
    n_series = counts_array.shape[0]
    bar_width = 0.8 / max(n_series, 1)

    for idx, series in enumerate(counts_array):
        offset = idx * bar_width
        ax.bar(
            indices + offset,
            series,
            width=bar_width,
            label=labels[idx],
            color=colors[idx] if colors is not None and idx < len(colors) else None,
            alpha=bar_alpha,
        )

    ax.set_title(title if title is not None else "Grouped Histogram")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_xticks(indices + bar_width * (n_series - 1) / 2)
    ax.set_xticklabels(categories)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.legend()

    if save and filename is not None:
        _save_figure(fig, filename)
    if show:
        plt.show()
    else:
        plt.close(fig)

    return fig, ax


__all__ = ["plot_3d_paths", "plot_2d_series", "plot_grouped_histogram"]
