#!/usr/bin/env python3
"""
Compute asymmetry index AI = (L - R) / (L + R) for each lateralized region
in FreeSurfer aparc+aseg ASL stats.

Supports two input formats:

  1. Per-subject summary from `mri_segstats --sum ...` (whitespace-delimited
     table with `#` header lines). Output: CSV with columns region,L,R,AI.

  2. Group table from `asegstats2table --tablefile ...` (tab-delimited;
     first column = subject id, remaining columns = region means).
     Output: CSV with first column = subject id and one AI column per
     L/R region pair.

Lateralized pairs are matched by name:
    Left-<X>        <->  Right-<X>           (subcortical / aseg)
    ctx-lh-<X>      <->  ctx-rh-<X>          (cortical / aparc)
    wm-lh-<X>       <->  wm-rh-<X>           (white-matter parcels, if present)
Midline / non-lateralized regions are dropped.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

PAIR_RULES = [
    (re.compile(r"^Left-(.+)$"),   re.compile(r"^Right-(.+)$"),   "{}"),
    (re.compile(r"^ctx-lh-(.+)$"), re.compile(r"^ctx-rh-(.+)$"), "ctx-{}"),
    (re.compile(r"^wm-lh-(.+)$"),  re.compile(r"^wm-rh-(.+)$"),  "wm-{}"),
]


def region_pair_key(name: str):
    """Return (canonical_key, side) or None if region is not lateralized."""
    for left_re, right_re, fmt in PAIR_RULES:
        m = left_re.match(name)
        if m:
            return fmt.format(m.group(1)), "L"
        m = right_re.match(name)
        if m:
            return fmt.format(m.group(1)), "R"
    return None


def ai(left: float, right: float) -> float | str:
    denom = left + right
    if denom == 0:
        return ""
    return (left - right) / denom


def is_segstats_sum(path: Path) -> bool:
    """A mri_segstats --sum file starts with `# Title Segmentation Statistics`
    or at least contains `# ColHeaders` lines."""
    with path.open() as fh:
        for line in fh:
            if line.startswith("# ColHeaders"):
                return True
            if not line.startswith("#"):
                return False
    return False


def parse_segstats(path: Path) -> dict[str, float]:
    """Return {StructName: Mean} from a mri_segstats --sum file."""
    headers: list[str] = []
    means: dict[str, float] = {}
    with path.open() as fh:
        for line in fh:
            if line.startswith("# ColHeaders"):
                headers = line.replace("# ColHeaders", "").split()
                continue
            if line.startswith("#") or not line.strip():
                continue
            if not headers:
                raise RuntimeError(f"{path}: no '# ColHeaders' line found")
            fields = line.split()
            row = dict(zip(headers, fields))
            name = row["StructName"]
            means[name] = float(row["Mean"])
    return means


def parse_group_table(path: Path) -> tuple[str, list[str], list[list[str]]]:
    """Return (id_col, region_cols, rows) from an asegstats2table file."""
    with path.open() as fh:
        reader = csv.reader(fh, delimiter="\t")
        header = next(reader)
        rows = [r for r in reader if r]
    id_col = header[0]
    region_cols = header[1:]
    return id_col, region_cols, rows


def collect_pairs(region_names):
    """Group region names into {canonical_key: {'L': name, 'R': name}}."""
    pairs: dict[str, dict[str, str]] = {}
    for name in region_names:
        keyside = region_pair_key(name)
        if keyside is None:
            continue
        key, side = keyside
        pairs.setdefault(key, {})[side] = name
    return {k: v for k, v in pairs.items() if "L" in v and "R" in v}


def write_per_subject(path: Path, means: dict[str, float], out_path: Path) -> None:
    pairs = collect_pairs(means.keys())
    with out_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["region", "left", "right", "AI"])
        for key in sorted(pairs):
            left_name = pairs[key]["L"]
            right_name = pairs[key]["R"]
            l = means.get(left_name, 0.0)
            r = means.get(right_name, 0.0)
            w.writerow([key, l, r, ai(l, r)])
    print(f"wrote {out_path} ({len(pairs)} region pairs)")


def write_group(path: Path, out_path: Path) -> None:
    id_col, region_cols, rows = parse_group_table(path)
    pairs = collect_pairs(region_cols)
    col_index = {c: i for i, c in enumerate(region_cols)}
    keys = sorted(pairs)

    with out_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([id_col] + [f"AI_{k}" for k in keys])
        for row in rows:
            subj = row[0]
            values = row[1:]
            out_row = [subj]
            for key in keys:
                l_idx = col_index[pairs[key]["L"]]
                r_idx = col_index[pairs[key]["R"]]
                try:
                    l = float(values[l_idx])
                    r = float(values[r_idx])
                except (ValueError, IndexError):
                    out_row.append("")
                    continue
                out_row.append(ai(l, r))
            w.writerow(out_row)
    print(f"wrote {out_path} ({len(rows)} subjects, {len(keys)} region pairs)")


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        print("usage: compute_asymmetry.py <input> <output.csv>", file=sys.stderr)
        return 2

    in_path = Path(argv[1])
    out_path = Path(argv[2])
    if not in_path.exists():
        print(f"input not found: {in_path}", file=sys.stderr)
        return 1

    if is_segstats_sum(in_path):
        means = parse_segstats(in_path)
        write_per_subject(in_path, means, out_path)
    else:
        write_group(in_path, out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
