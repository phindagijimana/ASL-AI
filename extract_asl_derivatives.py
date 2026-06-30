#!/usr/bin/env python3
"""
Extract two derivatives from a BIDS-ASL 4D series:

  1. mean control      -- mean of all 'control' volumes; high SNR, T2-like
                          contrast; used as bbregister --mov.
  2. mean deltaM       -- mean of (control - label) pair differences; the
                          perfusion-weighted signal. Used as the
                          measurement image for per-region statistics.

Both inherit the affine of the raw 4D ASL series, so the LTA produced by
bbregister on the mean-control image applies directly to the mean-deltaM
image (no second registration needed).

Usage:
    extract_asl_derivatives.py <bids_root> <sub_id> <acq_label>

Outputs:
    <bids_root>/derivatives/asl-mean-control/<sub>/perf/
        <sub>_acq-<acq>_desc-meanControl_asl.{nii.gz,json}
    <bids_root>/derivatives/asl-mean-deltam/<sub>/perf/
        <sub>_acq-<acq>_desc-meanDeltaM_asl.{nii.gz,json}

Idempotent. Why not the scanner CBF? On Siemens classic-DICOM
pcasl_3d_singleTI, the derived Perfusion_Weighted series lacks
ImageOrientationPatient, so dcm2niix produces a corrupted spatial
matrix (the "Bogus spatial matrix" warning). Using the in-house
deltaM, which inherits the raw ASL affine, avoids that risk.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import nibabel as nib
import numpy as np


def parse_aslcontext(path: Path) -> list[str]:
    with path.open() as fh:
        return [r["volume_type"] for r in csv.DictReader(fh, delimiter="\t")]


def write_derivative(out_nii: Path, data: np.ndarray, ref_img,
                     description: str, raw_rel: str, extra: dict) -> None:
    out_nii.parent.mkdir(parents=True, exist_ok=True)
    new = nib.Nifti1Image(data.astype(np.float32), ref_img.affine, ref_img.header)
    new.set_data_dtype(np.float32)
    nib.save(new, out_nii)
    side = out_nii.with_suffix("").with_suffix(".json")
    side.write_text(json.dumps({
        "Description": description,
        "Sources":     [f"bids:raw:{raw_rel}"],
        "RawSources":  [f"bids:raw:{raw_rel}"],
        **extra,
    }, indent=2) + "\n")


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__)
        return 2
    bids_root = Path(argv[1])
    sub = argv[2]
    acq = argv[3]

    perf = bids_root / sub / "perf"
    asl_nii = perf / f"{sub}_acq-{acq}_asl.nii.gz"
    asl_ctx = perf / f"{sub}_acq-{acq}_aslcontext.tsv"
    for f in (asl_nii, asl_ctx):
        if not f.exists():
            sys.exit(f"missing: {f}")

    raw_rel = f"{sub}/perf/{sub}_acq-{acq}_asl.nii.gz"
    out_ctrl = bids_root / "derivatives" / "asl-mean-control" / sub / "perf" / \
               f"{sub}_acq-{acq}_desc-meanControl_asl.nii.gz"
    out_delta = bids_root / "derivatives" / "asl-mean-deltam" / sub / "perf" / \
                f"{sub}_acq-{acq}_desc-meanDeltaM_asl.nii.gz"

    have_ctrl = out_ctrl.exists() and out_ctrl.with_suffix("").with_suffix(".json").exists()
    have_delta = out_delta.exists() and out_delta.with_suffix("").with_suffix(".json").exists()
    if have_ctrl and have_delta:
        print(f"already exists: both derivatives for {sub} {acq}")
        return 0

    types = parse_aslcontext(asl_ctx)
    ctrl_idx = [i for i, t in enumerate(types) if t == "control"]
    label_idx = [i for i, t in enumerate(types) if t == "label"]
    if not ctrl_idx:
        sys.exit(f"no control volumes in {asl_ctx}")
    if len(ctrl_idx) != len(label_idx):
        sys.exit(
            f"label/control count mismatch in {asl_ctx}: "
            f"{len(label_idx)} label vs {len(ctrl_idx)} control"
        )
    # Pair them in order of appearance (label-then-control is the standard
    # Siemens pcasl_3d_singleTI order; aslcontext.tsv preserves acquisition
    # order, so zip() gives the correct pairing).
    pairs = list(zip(label_idx, ctrl_idx))

    img = nib.load(asl_nii)
    if img.ndim != 4:
        sys.exit(f"{asl_nii} is not 4D (shape={img.shape})")
    n_vols = img.shape[3]
    if max(ctrl_idx + label_idx) >= n_vols:
        sys.exit(f"aslcontext indexes beyond ASL volumes ({n_vols})")
    data = img.get_fdata()

    if not have_ctrl:
        mean_ctrl = data[..., ctrl_idx].mean(axis=-1)
        write_derivative(
            out_ctrl, mean_ctrl, img,
            description=(
                f"Voxel-wise mean of {len(ctrl_idx)} control volumes from the raw "
                f"{acq} ASL series. Used as bbregister --mov because control volumes "
                f"have higher SNR and stronger anatomical contrast than label/control "
                f"differences."
            ),
            raw_rel=raw_rel,
            extra={"ControlVolumeIndices": ctrl_idx},
        )
        print(f"wrote {out_ctrl}  (mean of {len(ctrl_idx)} control volumes)")

    if not have_delta:
        # deltaM_per_pair = control_i - label_i; average across pairs.
        diffs = np.stack(
            [data[..., c] - data[..., l] for l, c in pairs], axis=-1
        )
        mean_delta = diffs.mean(axis=-1)
        write_derivative(
            out_delta, mean_delta, img,
            description=(
                f"Voxel-wise mean of {len(pairs)} (control - label) differences from "
                f"the raw {acq} ASL series. Perfusion-weighted; uncalibrated (no M0 "
                f"division). Asymmetry-index (L-R)/(L+R) of this image equals that of "
                f"the calibrated CBF map since M0 normalization is uniform across "
                f"hemispheres."
            ),
            raw_rel=raw_rel,
            extra={
                "LabelControlPairs": [list(p) for p in pairs],
                "Units": "arbitrary (uncalibrated perfusion signal)",
            },
        )
        print(f"wrote {out_delta}  (mean of {len(pairs)} control-label differences)")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
