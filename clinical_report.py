#!/usr/bin/env python3
"""Clinical PDF report for regional ASL asymmetry index results."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple, Union

import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from report_viz import LeanFigure, generate_report_figures, load_ai_csv

REPO_ROOT = Path(__file__).resolve().parent


def default_report_dir(subject: str) -> Path:
    """Deliverables path: ASL-AI/outputs/<subject>/reports/."""
    return REPO_ROOT / "outputs" / subject / "reports"


NAVY = colors.HexColor("#0B1F3A")
NAVY_MID = colors.HexColor("#163556")
NAVY_LIGHT = colors.HexColor("#E8EEF5")
NAVY_MUTED = colors.HexColor("#5A6F8A")
WHITE = colors.white
ROW_ALT = colors.HexColor("#F3F6FA")
CAVEAT_BG = colors.HexColor("#EEF3F9")

KEY_ROIS: Tuple[Tuple[str, str], ...] = (
    ("Thalamus", "Thalamus"),
    ("Hippocampus", "Hippocampus"),
    ("Amygdala", "Amygdala"),
    ("ctx-entorhinal", "Entorhinal cortex"),
    ("ctx-middletemporal", "Middle temporal"),
    ("ctx-insula", "Insula"),
    ("Caudate", "Caudate"),
)

_REPORT_TITLE = "Regional ASL Asymmetry Index Summary"

_AI_FORMULA = (
    "AI = (L−R)/(L+R) on mean control ASL signal in each FreeSurfer aparc+aseg region."
)

_LEAN_FIGURE_BLURB: Dict[str, str] = {
    "subcortical": "Subcortical ASL asymmetry (key deep-gray-matter regions).",
    "cortical": "Top cortical ASL asymmetry by region.",
    "none": "",
}

_AI_DEFINITION = (
    "Left–right asymmetry in mean control ASL signal within the paired atlas region."
)

_FIGURE_CAPTIONS: Dict[str, str] = {
    "subcortical_ai.png": "Subcortical ASL asymmetry (key deep-gray-matter regions).",
    "cortical_ai_top.png": "Top cortical regions by absolute ASL asymmetry.",
    "top_asymmetry.png": "Regions with largest absolute ASL asymmetry (|AI|).",
    "cortical_ai.png": "Cortical ASL asymmetry for all Desikan–Killiany regions.",
    "subcortical_panel.png": "Subcortical mean control ASL (L vs R) and asymmetry index.",
}

_LEAN_FIGURE_SECTIONS: Dict[str, Tuple[str, str]] = {
    "subcortical_ai.png": ("Subcortical Asymmetry", "subcortical_ai.png"),
    "cortical_ai_top.png": ("Cortical Asymmetry", "cortical_ai_top.png"),
}

_TABLE_STYLE = TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), NAVY),
    ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
    ("FONTSIZE", (0, 0), (-1, -1), 9),
    ("GRID", (0, 0), (-1, -1), 0.4, NAVY_MID),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("ALIGN", (1, 1), (-1, -1), "LEFT"),
    ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ("TOPPADDING", (0, 0), (-1, -1), 5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, ROW_ALT]),
])

_ACQ_RE = re.compile(r"_acq-([^_]+)_AI\.csv$", re.IGNORECASE)


def _fmt_ai(value: float) -> str:
    if not np.isfinite(value):
        return "—"
    direction = "L > R" if value > 0 else ("R > L" if value < 0 else "symmetric")
    return f"{value:+.3f} ({direction})"


def _fmt_signal(value: float) -> str:
    if not np.isfinite(value):
        return "—"
    return f"{value:.1f}"


def _acq_from_csv(path: Path) -> Optional[str]:
    match = _ACQ_RE.search(path.name)
    return match.group(1) if match else None


def _acq_label(acq: Optional[str]) -> str:
    if not acq:
        return ""
    labels = {
        "singleTI": "PLD 1.8 s",
        "singleTI2100": "PLD 2.1 s",
    }
    return labels.get(acq, acq)


def _load_provenance(path: Optional[Path]) -> dict:
    if path is None or not path.is_file():
        return {}
    with open(path) as f:
        return json.load(f)


def _bbregister_cost(provenance: dict, acq: Optional[str]) -> Optional[float]:
    if acq:
        acq_block = provenance.get("acquisitions", {}).get(acq, {})
        raw = acq_block.get("bbregister_mincost")
        if raw is not None:
            try:
                return float(str(raw).split()[0])
            except (TypeError, ValueError, IndexError):
                pass
    raw = provenance.get("bbregister_mincost")
    if raw is None:
        return None
    try:
        return float(str(raw).split()[0])
    except (TypeError, ValueError, IndexError):
        return None


def _pld_seconds(provenance: dict, acq: Optional[str]) -> Optional[float]:
    if not acq:
        return None
    acq_block = provenance.get("acquisitions", {}).get(acq, {})
    pld = acq_block.get("pld_seconds")
    if pld is None:
        return None
    try:
        return float(pld)
    except (TypeError, ValueError):
        return None


def _top_asymmetry(ai: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    return ai.sort_values("abs_ai", ascending=False).head(n)


def _key_metrics(ai: pd.DataFrame, *, lean: bool) -> Tuple[List[Dict[str, str]], List[str]]:
    if lean:
        headers = ["Structure", "AI"]
    else:
        headers = ["Structure", "AI", "Left mean", "Right mean"]
    rows: List[Dict[str, str]] = []
    for roi_key, label in KEY_ROIS:
        match = ai.loc[ai["region"] == roi_key]
        if match.empty:
            entry = {"label": label, "ai": "—", "left": "—", "right": "—"}
        else:
            row = match.iloc[0]
            entry = {
                "label": label,
                "ai": _fmt_ai(float(row["asymmetry_index"])),
                "left": _fmt_signal(float(row["left_mean"])),
                "right": _fmt_signal(float(row["right_mean"])),
            }
        rows.append(entry)
    return rows, headers


def _metrics_table_rows(metrics: List[Dict[str, str]], headers: List[str]) -> List[List[str]]:
    key_map = {
        "Structure": "label",
        "AI": "ai",
        "Left mean": "left",
        "Right mean": "right",
    }
    return [[m[key_map[h]] for h in headers] for m in metrics]


def _simple_table(headers: List[str], rows: List[List[str]], col_widths: List[float]) -> Table:
    table = Table([headers, *rows], colWidths=col_widths)
    table.setStyle(_TABLE_STYLE)
    return table


def _key_structures_table(
    headers: List[str],
    metrics: List[Dict[str, str]],
    *,
    def_style: ParagraphStyle,
    include_definitions: bool,
) -> Table:
    data_rows = _metrics_table_rows(metrics, headers)
    if include_definitions:
        def_row: List[Union[str, Paragraph]] = [""]
        for h in headers[1:]:
            if h == "AI":
                def_row.append(Paragraph(_AI_DEFINITION, def_style))
            else:
                def_row.append("")
        data: List[List[Union[str, Paragraph]]] = [headers, def_row, *data_rows]
        first_data_row = 2
    else:
        data = [headers, *data_rows]
        first_data_row = 1

    col_width = 7.3 * inch / len(headers)
    table = Table(data, colWidths=[col_width] * len(headers))
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, first_data_row), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, first_data_row), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, NAVY_MID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, first_data_row), (-1, -1), "LEFT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, first_data_row), (-1, -1), [WHITE, ROW_ALT]),
    ]
    if include_definitions:
        style_cmds.extend([
            ("BACKGROUND", (0, 1), (-1, 1), NAVY_LIGHT),
            ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Oblique"),
            ("FONTSIZE", (0, 1), (-1, 1), 7),
            ("TEXTCOLOR", (0, 1), (-1, 1), NAVY_MUTED),
        ])
    table.setStyle(TableStyle(style_cmds))
    return table


def _figure_story(
    fig_path: Path,
    caption: str,
    body_style: ParagraphStyle,
    max_width: float = 6.5 * inch,
    *,
    show_caption: bool = True,
) -> List:
    if not fig_path.is_file():
        return []
    img = Image(str(fig_path))
    iw, ih = img.imageWidth, img.imageHeight
    if iw <= 0:
        return []
    scale = min(max_width / iw, 1.0)
    img.drawWidth = iw * scale
    img.drawHeight = ih * scale
    out: List = [img, Spacer(1, 0.05 * inch)]
    if show_caption and caption:
        out.append(Paragraph(caption, ParagraphStyle(
            "FigCaption", parent=body_style, fontSize=8, textColor=NAVY_MUTED,
        )))
        out.append(Spacer(1, 0.12 * inch))
    return out


def _draw_page_chrome(canv: pdfcanvas.Canvas, doc: SimpleDocTemplate) -> None:
    page_w, page_h = letter
    canv.saveState()

    header_h = 0.55 * inch
    canv.setFillColor(NAVY)
    canv.rect(0, page_h - header_h, page_w, header_h, fill=1, stroke=0)

    canv.setStrokeColor(NAVY_MID)
    canv.setLineWidth(2)
    canv.line(0.6 * inch, 0.55 * inch, page_w - 0.6 * inch, 0.55 * inch)

    canv.setFillColor(NAVY_MUTED)
    canv.setFont("Helvetica", 8)
    canv.drawString(0.6 * inch, 0.35 * inch, "Research use only")
    canv.drawRightString(page_w - 0.6 * inch, 0.35 * inch, f"Page {doc.page}")

    canv.restoreState()


def _full_report_figures(fig_dir: Path) -> Tuple[Tuple[str, Tuple[str, ...]], ...]:
    pages: List[Tuple[str, Tuple[str, ...]]] = []
    if (fig_dir / "cortical_ai.png").is_file():
        pages.append(("Cortical Asymmetry", ("cortical_ai.png",)))
    if (fig_dir / "subcortical_panel.png").is_file():
        pages.append(("Subcortical Summary", ("subcortical_panel.png",)))
    if (fig_dir / "top_asymmetry.png").is_file():
        pages.append(("Top Asymmetry", ("top_asymmetry.png",)))
    return tuple(pages)


def _lean_report_figure(fig_dir: Path, lean_figure: LeanFigure) -> Optional[Tuple[str, str]]:
    if lean_figure == "subcortical":
        name = "subcortical_ai.png"
    elif lean_figure == "cortical":
        name = "cortical_ai_top.png"
    else:
        return None
    if not (fig_dir / name).is_file():
        return None
    section, _ = _LEAN_FIGURE_SECTIONS[name]
    return section, name


def _note_block(
    subject: str,
    acq: Optional[str],
    *,
    lean: bool,
    lean_figure: LeanFigure,
    caveat_style: ParagraphStyle,
    formula_style: ParagraphStyle,
    figure_blurb_style: ParagraphStyle,
) -> List:
    acq_text = _acq_label(acq)
    acq_clause = f" ({acq_text})" if acq_text else ""
    csv_hint = f"outputs/{subject}/stats/*_AI.csv"
    if lean:
        note = (
            f"<b>Note:</b> Raw regional ASL asymmetry from mean control images{acq_clause} "
            "(not normative z-scores). Research use only."
        )
    else:
        note = (
            f"<b>Note:</b> AI values are raw asymmetry indices from mean control ASL "
            f"registered to T1{acq_clause} (not normative z-scores). Interpret alongside "
            f"clinical history and MRI. Full regional data: {csv_hint}. Research use only."
        )

    blocks: List = [Paragraph(note, caveat_style)]

    if lean:
        blurb = _LEAN_FIGURE_BLURB.get(lean_figure, "")
        if blurb:
            blocks.append(Paragraph(blurb, figure_blurb_style))
        blocks.append(Paragraph(_AI_FORMULA, formula_style))
    else:
        blocks.append(Paragraph(_AI_FORMULA, formula_style))

    return blocks


def _qc_paragraph(
    provenance: dict,
    acq: Optional[str],
    body_style: ParagraphStyle,
) -> Optional[Paragraph]:
    cost = _bbregister_cost(provenance, acq)
    if cost is None:
        return None
    if cost <= 0.7:
        text = f"<b>Registration QC:</b> bbregister cost = {cost:.3f}."
    else:
        text = (
            f"<b>Registration QC:</b> bbregister cost = {cost:.3f} "
            "(> 0.7 — verify ASL–T1 alignment)."
        )
    return Paragraph(text, ParagraphStyle(
        "QC", parent=body_style, fontSize=9, backColor=CAVEAT_BG,
        borderColor=NAVY_MID, borderWidth=1, borderPadding=8,
        spaceBefore=4, spaceAfter=8,
    ))


def generate_clinical_report(
    ai_csv: Path,
    *,
    provenance_json: Optional[Path] = None,
    out_dir: Optional[Path] = None,
    with_figures: bool = True,
    lean: bool = True,
    lean_figure: LeanFigure = "subcortical",
    acq: Optional[str] = None,
    version: str = "1.0.0",
) -> Path:
    """Write ``report.pdf`` under ``out_dir`` (default: ASL-AI/outputs/<subject>/reports/)."""
    ai_csv = ai_csv.resolve()
    ai = load_ai_csv(ai_csv)
    subject = str(ai["subject"].iloc[0]) if "subject" in ai.columns and len(ai) else ai_csv.parent.parent.name
    acq = acq or _acq_from_csv(ai_csv)

    prov = _load_provenance(provenance_json)
    if provenance_json is None:
        candidate = ai_csv.parent / "asl-ai.provenance.json"
        if candidate.is_file():
            prov = _load_provenance(candidate)

    if out_dir is None:
        out_dir = default_report_dir(subject)
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "report.pdf"
    fig_dir = out_dir / "figures"

    if with_figures:
        generate_report_figures(
            ai_csv, fig_dir, full=not lean, lean_figure=lean_figure,
        )

    metrics, key_headers = _key_metrics(ai, lean=lean)
    top = _top_asymmetry(ai, n=5)

    ts_end = prov.get("timestamp_end_utc") or prov.get("timestamp_archive_utc", "")
    generated = ts_end.replace("T", " ").replace("Z", " UTC") if ts_end else datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle", parent=styles["Heading1"],
        fontName="Helvetica-Bold", fontSize=18, textColor=NAVY,
        spaceAfter=4, spaceBefore=4, leading=22,
    )
    meta_style = ParagraphStyle(
        "Meta", parent=styles["Normal"],
        fontSize=9, textColor=NAVY_MUTED, leading=12, spaceAfter=8,
    )
    section_style = ParagraphStyle(
        "Section", parent=styles["Heading2"],
        fontName="Helvetica-Bold", fontSize=11, textColor=NAVY,
        spaceBefore=12, spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["Normal"],
        fontSize=10, leading=13, textColor=NAVY,
    )
    caveat_style = ParagraphStyle(
        "Caveat", parent=body_style, fontSize=9, leading=12,
        backColor=CAVEAT_BG, borderColor=NAVY_MID, borderWidth=1,
        borderPadding=8, spaceBefore=4, spaceAfter=12,
    )
    ai_def_style = ParagraphStyle(
        "AiDef", parent=body_style, fontSize=7, leading=9, textColor=NAVY_MUTED,
    )
    formula_style = ParagraphStyle(
        "Formula", parent=meta_style, fontSize=8, leading=10,
        spaceBefore=2, spaceAfter=8,
    )
    figure_blurb_style = ParagraphStyle(
        "FigBlurb", parent=body_style, fontSize=9, leading=11,
        spaceBefore=4, spaceAfter=2, textColor=NAVY,
    )

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=letter,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.85 * inch,
        bottomMargin=0.75 * inch,
        title=_REPORT_TITLE,
        author="ASL-AI",
    )

    acq_label = _acq_label(acq)
    pld = _pld_seconds(prov, acq)
    acq_meta = acq_label
    if pld is not None and acq_label and f"{pld:g}" not in acq_label:
        acq_meta = f"{acq_label} ({pld:g} s PLD)"

    if lean:
        meta_parts = [f"<b>{subject}</b>", f"Generated {generated}", f"ASL-AI {version}"]
        if acq_meta:
            meta_parts.insert(1, acq_meta)
        meta_line = "  ·  ".join(meta_parts)
    else:
        fs_build = prov.get("freesurfer_build", "FreeSurfer aparc+aseg")
        meta_parts = [f"<b>{subject}</b>", f"Generated {generated}", f"ASL-AI {version}", fs_build]
        if acq_meta:
            meta_parts.insert(1, acq_meta)
        meta_line = "  ·  ".join(meta_parts)

    story: List = [
        Paragraph(_REPORT_TITLE, title_style),
        Paragraph(meta_line, meta_style),
    ]
    story.extend(_note_block(
        subject, acq, lean=lean, lean_figure=lean_figure,
        caveat_style=caveat_style, formula_style=formula_style,
        figure_blurb_style=figure_blurb_style,
    ))

    if not lean:
        qc = _qc_paragraph(prov, acq, body_style)
        if qc is not None:
            story.append(qc)

    if not lean:
        mean_abs = float(ai["abs_ai"].mean())
        max_abs = float(ai["abs_ai"].max())
        max_region = str(ai.loc[ai["abs_ai"].idxmax(), "region"])
        story.append(Paragraph(
            f"Summary: mean |AI| = {mean_abs:.3f}, max |AI| = {max_abs:.3f} ({max_region}).",
            meta_style,
        ))

    story.append(Paragraph("Key Structures", section_style))
    story.append(_key_structures_table(
        key_headers, metrics,
        def_style=ai_def_style,
        include_definitions=not lean,
    ))
    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph("Top 5 ASL Asymmetry", section_style))

    top_rows = [
        [
            str(i + 1),
            str(row.region),
            f"{float(row.asymmetry_index):+.3f}",
            *( [] if lean else [str(row.region_type)] ),
        ]
        for i, row in top.reset_index(drop=True).iterrows()
    ]
    if lean:
        top_table = _simple_table(
            ["#", "Region", "AI"],
            top_rows,
            [0.4 * inch, 4.3 * inch, 1.2 * inch],
        )
    else:
        top_table = _simple_table(
            ["#", "Region", "AI", "Type"],
            top_rows,
            [0.4 * inch, 2.8 * inch, 1.0 * inch, 1.1 * inch],
        )
    story.extend([top_table, Spacer(1, 0.15 * inch)])

    if with_figures:
        if lean:
            lean_fig = _lean_report_figure(fig_dir, lean_figure)
            if lean_fig:
                _, fig_name = lean_fig
                block: List = []
                block.extend(_figure_story(
                    fig_dir / fig_name, "", body_style, show_caption=False,
                ))
                story.append(KeepTogether(block))
        else:
            report_pages = _full_report_figures(fig_dir)
            if report_pages:
                story.append(PageBreak())
                for section_title, names in report_pages:
                    block = [Paragraph(section_title, section_style)]
                    for name in names:
                        block.extend(_figure_story(
                            fig_dir / name,
                            _FIGURE_CAPTIONS.get(name, name),
                            body_style,
                        ))
                    story.append(KeepTogether(block))

    if not lean:
        story.append(Paragraph(
            _AI_FORMULA,
            ParagraphStyle("FooterNote", parent=meta_style, fontSize=8, spaceBefore=10),
        ))

    doc.build(story, onFirstPage=_draw_page_chrome, onLaterPages=_draw_page_chrome)
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ai-csv", type=Path, required=True, help="stats/*_AI.csv")
    ap.add_argument("--provenance", type=Path, default=None, help="stats/asl-ai.provenance.json")
    ap.add_argument(
        "--out-dir", type=Path, default=None,
        help="Output directory (default: ASL-AI/outputs/<subject>/reports/)",
    )
    ap.add_argument("--acq", default=None, help="Acquisition key (e.g. singleTI); inferred from CSV name if omitted")
    ap.add_argument("--no-figures", action="store_true", help="Skip matplotlib figures")
    ap.add_argument(
        "--full", action="store_true",
        help="Verbose report (all figures, L/R means, summary stats)",
    )
    ap.add_argument(
        "--figure", choices=("subcortical", "cortical", "none"), default="subcortical",
        help="Single figure for lean report (default: subcortical)",
    )
    args = ap.parse_args()

    path = generate_clinical_report(
        args.ai_csv,
        provenance_json=args.provenance,
        out_dir=args.out_dir,
        with_figures=not args.no_figures,
        lean=not args.full,
        lean_figure=args.figure,
        acq=args.acq,
    )
    print(path)


if __name__ == "__main__":
    main()
