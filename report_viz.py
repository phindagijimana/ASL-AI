"""Matplotlib figures for ASL-AI clinical PDF reports."""

from __future__ import annotations

from pathlib import Path
from typing import List, Literal, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

LeanFigure = Literal["subcortical", "cortical", "none"]

_SUBCORTICAL_ORDER: List[str] = [
    "Thalamus",
    "Caudate",
    "Putamen",
    "Pallidum",
    "Hippocampus",
    "Amygdala",
    "Accumbens-area",
]

_POS_AI = "#C44E52"
_NEG_AI = "#4C72B0"
_LEFT = "#4C72B0"
_RIGHT = "#DD8452"


def _adaptive_ai_ylim(
    values: List[float],
    *,
    default_half_span: float = 0.06,
    pad: float = 1.12,
    max_half_span: float = 1.0,
) -> Tuple[float, float]:
    if not values:
        return (-default_half_span, default_half_span)
    max_abs = max(abs(float(v)) for v in values)
    if max_abs <= default_half_span:
        half = default_half_span
    else:
        half = min(max_abs * pad, max_half_span)
    return (-half, half)


def _short_label(name: str, max_len: int = 24) -> str:
    label = name.replace("ctx-", "").replace("-", " ")
    if len(label) > max_len:
        return label[: max_len - 1] + "…"
    return label


def _save_fig(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close()
    return path


def _region_type(region: str) -> str:
    if region.startswith("ctx-"):
        return "cortex"
    return "subcortical"


def load_ai_csv(path: Path) -> pd.DataFrame:
    """Load ASL AI CSV (region,left,right,AI) or PET-style columns."""
    df = pd.read_csv(path)
    rename = {}
    if "left" in df.columns and "left_mean" not in df.columns:
        rename["left"] = "left_mean"
    if "right" in df.columns and "right_mean" not in df.columns:
        rename["right"] = "right_mean"
    if "AI" in df.columns and "asymmetry_index" not in df.columns:
        rename["AI"] = "asymmetry_index"
    if rename:
        df = df.rename(columns=rename)
    if "subject" not in df.columns:
        df["subject"] = path.parent.parent.name
    df["region_type"] = df["region"].map(_region_type)
    df["abs_ai"] = df["asymmetry_index"].abs()
    return df


def plot_top_asymmetry(
    ai: pd.DataFrame,
    out_path: Path,
    *,
    top_n: int = 10,
    title: str = "Top absolute ASL asymmetry (all regions)",
) -> Path:
    df = ai.nlargest(top_n, "abs_ai").sort_values("abs_ai", ascending=True)
    bar_colors = [_POS_AI if v > 0 else _NEG_AI for v in df["asymmetry_index"]]
    y = np.arange(len(df))
    fig, ax = plt.subplots(figsize=(8, 5.5))
    ax.barh(y, df["asymmetry_index"], color=bar_colors, alpha=0.85)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_yticks(y)
    ax.set_yticklabels(
        [_short_label(f"{r.region} ({r.region_type[:4]})") for r in df.itertuples()],
        fontsize=8,
    )
    ax.set_xlim(-1, 1)
    ax.set_xlabel("AI = (L − R) / (L + R)")
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.grid(axis="x", alpha=0.25)
    return _save_fig(out_path)


def plot_cortical_ai(
    ai: pd.DataFrame,
    out_path: Path,
    *,
    title: str = "Cortical ASL asymmetry by region",
) -> Path:
    cortex = ai.loc[ai["region_type"] == "cortex"].copy()
    cortex = cortex.sort_values("abs_ai", ascending=False)
    y = np.arange(len(cortex))
    bar_colors = [_POS_AI if v > 0 else _NEG_AI for v in cortex["asymmetry_index"]]
    fig, ax = plt.subplots(figsize=(8.5, 10))
    ax.barh(y, cortex["asymmetry_index"], color=bar_colors, alpha=0.85)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_yticks(y)
    ax.set_yticklabels([_short_label(str(n)) for n in cortex["region"]], fontsize=7)
    ax.invert_yaxis()
    ax.set_xlim(-1, 1)
    ax.set_xlabel("AI = (L − R) / (L + R)")
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.grid(axis="x", alpha=0.25)
    return _save_fig(out_path)


def plot_cortical_ai_top(
    ai: pd.DataFrame,
    out_path: Path,
    *,
    top_n: int = 12,
    title: str = "Top cortical ASL asymmetry",
) -> Path:
    cortex = ai.loc[ai["region_type"] == "cortex"].nlargest(top_n, "abs_ai")
    cortex = cortex.sort_values("abs_ai", ascending=True)
    y = np.arange(len(cortex))
    vals = cortex["asymmetry_index"].tolist()
    ylo, yhi = _adaptive_ai_ylim(vals)
    bar_colors = [_POS_AI if v > 0 else _NEG_AI for v in cortex["asymmetry_index"]]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(
        y, cortex["asymmetry_index"], height=0.72, color=bar_colors,
        alpha=0.92, edgecolor="#333333", linewidth=0.6,
    )
    ax.axvline(0, color="black", linewidth=0.9)
    ax.set_yticks(y)
    ax.set_yticklabels([_short_label(str(n)) for n in cortex["region"]], fontsize=8)
    ax.set_xlim(ylo, yhi)
    ax.set_xlabel("AI = (L − R) / (L + R)")
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.grid(axis="x", alpha=0.25)
    return _save_fig(out_path)


def plot_subcortical_ai(
    ai: pd.DataFrame,
    out_path: Path,
    *,
    title: str = "Subcortical ASL asymmetry",
) -> Path:
    rows = []
    for name in _SUBCORTICAL_ORDER:
        match = ai.loc[ai["region"] == name]
        if match.empty:
            continue
        rows.append({
            "region": name,
            "asymmetry_index": float(match.iloc[0]["asymmetry_index"]),
        })
    if not rows:
        return out_path
    df = pd.DataFrame(rows)
    x = np.arange(len(df))
    vals = df["asymmetry_index"].tolist()
    ylo, yhi = _adaptive_ai_ylim(vals)
    bar_colors = [_POS_AI if v > 0 else _NEG_AI for v in df["asymmetry_index"]]
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.bar(
        x, df["asymmetry_index"], width=0.72, color=bar_colors,
        alpha=0.92, edgecolor="#333333", linewidth=0.6,
    )
    ax.axhline(0, color="black", linewidth=0.9)
    ax.set_xticks(x)
    ax.set_xticklabels([_short_label(n, 12) for n in df["region"]], rotation=35, ha="right")
    ax.set_ylim(ylo, yhi)
    ax.set_ylabel("AI")
    ax.grid(axis="y", alpha=0.3)
    ax.set_title(title, fontsize=11, fontweight="bold")
    return _save_fig(out_path)


def plot_subcortical_panel(
    ai: pd.DataFrame,
    out_path: Path,
) -> Path:
    rows = []
    for name in _SUBCORTICAL_ORDER:
        match = ai.loc[ai["region"] == name]
        if match.empty:
            continue
        row = match.iloc[0]
        rows.append({
            "region": name,
            "left_mean": float(row["left_mean"]),
            "right_mean": float(row["right_mean"]),
            "asymmetry_index": float(row["asymmetry_index"]),
        })
    if not rows:
        return out_path
    df = pd.DataFrame(rows)
    x = np.arange(len(df))
    width = 0.35
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5))

    ax0 = axes[0]
    ax0.bar(x - width / 2, df["left_mean"], width, label="Left", color=_LEFT)
    ax0.bar(x + width / 2, df["right_mean"], width, label="Right", color=_RIGHT)
    ax0.set_xticks(x)
    ax0.set_xticklabels([_short_label(n, 12) for n in df["region"]], rotation=35, ha="right")
    ax0.set_ylabel("Mean ASL signal")
    ax0.set_title("Subcortical mean control", fontweight="bold")
    ax0.legend(fontsize=8)
    ax0.grid(axis="y", alpha=0.25)

    ax1 = axes[1]
    bar_colors = [_POS_AI if v > 0 else _NEG_AI for v in df["asymmetry_index"]]
    ax1.bar(x, df["asymmetry_index"], color=bar_colors, alpha=0.85)
    ax1.axhline(0, color="black", linewidth=0.8)
    ax1.set_xticks(x)
    ax1.set_xticklabels([_short_label(n, 12) for n in df["region"]], rotation=35, ha="right")
    ax1.set_ylim(-1, 1)
    ax1.set_ylabel("AI")
    ax1.set_title("Subcortical asymmetry", fontweight="bold")
    ax1.grid(axis="y", alpha=0.25)

    fig.suptitle("Subcortical structures (FreeSurfer aparc+aseg)", fontsize=11, y=1.02)
    return _save_fig(out_path)


def generate_report_figures(
    ai_csv: Path,
    fig_dir: Path,
    *,
    full: bool = False,
    lean_figure: LeanFigure = "subcortical",
) -> List[Path]:
    ai = load_ai_csv(ai_csv)
    fig_dir.mkdir(parents=True, exist_ok=True)
    paths: List[Path] = []

    if full:
        paths.append(plot_top_asymmetry(ai, fig_dir / "top_asymmetry.png"))
        cortex = ai.loc[ai["region_type"] == "cortex"]
        if not cortex.empty:
            paths.append(plot_cortical_ai(cortex, fig_dir / "cortical_ai.png"))
        if ai.loc[ai["region"].isin(_SUBCORTICAL_ORDER)].shape[0]:
            paths.append(plot_subcortical_panel(ai, fig_dir / "subcortical_panel.png"))
        return paths

    if lean_figure == "subcortical":
        paths.append(plot_subcortical_ai(ai, fig_dir / "subcortical_ai.png"))
    elif lean_figure == "cortical":
        cortex = ai.loc[ai["region_type"] == "cortex"]
        if not cortex.empty:
            paths.append(plot_cortical_ai_top(cortex, fig_dir / "cortical_ai_top.png"))
    return paths
