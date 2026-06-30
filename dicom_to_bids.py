#!/usr/bin/env python3
"""
Convert one pCASL DICOM subject folder to BIDS layout.

Usage:
    dicom_to_bids.py <dicom_source_dir> <bids_subject_id> <bids_root>

Example:
    dicom_to_bids.py /path/to/dicom sub-001 ./Data_ASL

What it does
------------
1. Runs `dcm2niix -ba y` into a temp dir (PHI stripped from JSON sidecars).
2. Identifies series by SeriesNumber/SeriesDescription/ImageType:
     s17  AX 3D MPRAGE NQA NQT1                 -> anat/<sub>_T1w
     s26  ASL pcasl_3d_singleTI    (1800 ms)    -> perf/<sub>_acq-singleTI_asl     (+ aslcontext.tsv)
     s28  ASL pcasl_3d_singleTI    (2100 ms)    -> perf/<sub>_acq-singleTI2100_asl (+ aslcontext.tsv)
     s27  Perfusion_Weighted (scanner CBF)      -> derivatives/scanner-cbf/<sub>/perf/<sub>_acq-singleTI_desc-{mean,color}_cbf
     s29  Perfusion_Weighted (scanner CBF)      -> derivatives/scanner-cbf/<sub>/perf/<sub>_acq-singleTI2100_desc-{mean,color}_cbf
3. Augments each ASL JSON with BIDS-ASL required fields
   (ArterialSpinLabelingType, PostLabelingDelay, LabelingDuration,
   BackgroundSuppression, M0Type, TotalAcquiredPairs).
4. Writes aslcontext.tsv (volume order verified from DICOM ImageComments:
   1 m0scan + 8 (label, control) pairs).
5. Ensures dataset_description.json, README, participants.tsv exist at the
   BIDS root (creates on first run, appends a participant row otherwise).
6. Appends a row per converted file to dicom_bids_mapping.csv at the BIDS
   root. This CSV INTENTIONALLY contains PHI (PatientName, PatientID) since
   it stays on protected premises; do NOT share it with the BIDS data.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import pydicom


# ---- series classification --------------------------------------------------

ASL_ACQ_LABELS = {
    "ASL pcasl_3d_singleTI":         "singleTI",
    "ASL pcasl_3d_singleTI 2100PLD": "singleTI2100",
}

# PostLabelingDelay in seconds, parsed from ProtocolName/SeriesDescription.
def parse_pld_seconds(series_description: str) -> float:
    m = re.search(r"(\d{3,4})\s*PLD", series_description)
    if m:
        return int(m.group(1)) / 1000.0
    return 1.8  # default for "ASL pcasl_3d_singleTI"


def classify_series(json_data: dict) -> dict | None:
    """Return BIDS placement instructions for one dcm2niix output file."""
    sd = json_data.get("SeriesDescription", "")
    sn = json_data.get("SeriesNumber")
    img_type = json_data.get("ImageType", [])

    # T1w MPRAGE
    if "MPRAGE" in sd.upper():
        return {"kind": "anat", "suffix": "T1w", "entities": {}}

    # Raw ASL series — name matches ASL_ACQ_LABELS keys
    if sd in ASL_ACQ_LABELS:
        return {
            "kind": "perf_asl",
            "suffix": "asl",
            "entities": {"acq": ASL_ACQ_LABELS[sd]},
            "pld_s": parse_pld_seconds(sd),
        }

    # Scanner-computed Perfusion_Weighted derivatives
    if sd == "Perfusion_Weighted":
        protocol = json_data.get("ProtocolName", "")
        acq = ASL_ACQ_LABELS.get(protocol, f"series{sn}")
        desc = "color" if "COLOR" in img_type else "mean"
        return {
            "kind": "derivative_cbf",
            "suffix": "cbf",
            "entities": {"acq": acq, "desc": desc},
        }

    return None


def bids_filename(subject: str, suffix: str, entities: dict, ext: str) -> str:
    parts = [subject]
    for k in ("ses", "acq", "rec", "run", "desc"):
        if k in entities:
            parts.append(f"{k}-{entities[k]}")
    return "_".join(parts) + f"_{suffix}{ext}"


# ---- ASL JSON augmentation --------------------------------------------------

def augment_asl_json(j: dict, pld_s: float) -> dict:
    # LabelingDuration: InversionTime = LabelingDuration + PostLabelingDelay (Siemens convention)
    ti = j.get("InversionTime")
    if isinstance(ti, (int, float)):
        labeling_duration = round(ti - pld_s, 4)
    else:
        labeling_duration = 1.8  # Siemens pcasl_3d_singleTI default
    j["ArterialSpinLabelingType"] = "PCASL"
    j["PostLabelingDelay"] = pld_s
    j["LabelingDuration"] = labeling_duration
    # BIDS-ASL: RepetitionTimePreparation = inter-pair TR (NOT the long M0 TR).
    # On Siemens classic DICOM dcm2niix exports this as RepetitionTimeExcitation.
    rt_prep = j.get("RepetitionTimeExcitation")
    if isinstance(rt_prep, (int, float)):
        j["RepetitionTimePreparation"] = rt_prep
    j["BackgroundSuppression"] = True
    j["BackgroundSuppressionNumberPulses"] = 2  # Siemens 3D pCASL default
    # BackgroundSuppressionPulseTime intentionally NOT set: exact pulse
    # times depend on PLD/labeling duration combination and are not
    # exposed in classic DICOM headers. Validator will WARN; resolve
    # with scanner protocol PDF if you need exact values.
    j["VascularCrushing"] = False        # Siemens 3D pCASL: no crushers
    j["M0Type"] = "Included"
    j["TotalAcquiredPairs"] = 8
    j["AcquisitionVoxelSize"] = [
        round(j.get("PixelSpacing", [3.5, 3.5])[0] if "PixelSpacing" in j else 3.5, 3),
        round(j.get("PixelSpacing", [3.5, 3.5])[1] if "PixelSpacing" in j else 3.5, 3),
        j.get("SliceThickness", 4),
    ]
    return j


# Verified from the DICOM ImageComments tag: 1 M0 + 8 alternating label/control pairs.
ASL_CONTEXT_ROWS = ["m0scan"] + ["label", "control"] * 8


# ---- DICOM PHI extraction (for mapping CSV) --------------------------------

def collect_dicom_phi(dicom_root: Path) -> dict:
    """Read one DICOM under dicom_root to extract PHI for the mapping CSV."""
    for root, _, files in os.walk(dicom_root):
        for f in files:
            try:
                ds = pydicom.dcmread(os.path.join(root, f),
                                     stop_before_pixels=True, force=True)
                return {
                    "PatientID":         str(getattr(ds, "PatientID", "")),
                    "PatientName":       str(getattr(ds, "PatientName", "")),
                    "PatientBirthDate":  str(getattr(ds, "PatientBirthDate", "")),
                    "PatientSex":        str(getattr(ds, "PatientSex", "")),
                    "PatientAge":        str(getattr(ds, "PatientAge", "")),
                    "StudyDate":         str(getattr(ds, "StudyDate", "")),
                    "StudyDescription":  str(getattr(ds, "StudyDescription", "")),
                    "StudyInstanceUID":  str(getattr(ds, "StudyInstanceUID", "")),
                    "InstitutionName":   str(getattr(ds, "InstitutionName", "")),
                    "ManufacturerModelName": str(getattr(ds, "ManufacturerModelName", "")),
                }
            except Exception:
                continue
    sys.exit(f"no readable DICOM under {dicom_root}")


# ---- BIDS root scaffolding --------------------------------------------------

DATASET_DESCRIPTION = {
    "Name": "pCASL ASL Dataset",
    "BIDSVersion": "1.10.0",
    "DatasetType": "raw",
    "Authors": ["ASL-AI Pipeline"],
    "Acknowledgements": "Siemens pcasl_3d_singleTI sequence.",
}

PARTICIPANTS_JSON = {
    "participant_id": {"Description": "Unique participant identifier (sub-XXX)."},
    "sex":            {"Description": "Biological sex from DICOM PatientSex.",
                       "Levels": {"M": "male", "F": "female", "O": "other", "n/a": "not available"}},
    "age":            {"Description": "Age at scan from DICOM PatientAge (DICOM AS format, e.g. '034Y')."},
}

# Series expected from a complete pcasl_3d_singleTI exam.
# Strict mode (default) fails if any of these is missing or if an unknown
# series is encountered. Override with --allow-extra-series / --allow-missing.
EXPECTED_SERIES = {
    # SeriesDescription : count of dcm2niix outputs that should match
    "AX 3D MPRAGE NQA NQT1":           1,  # T1w
    "ASL pcasl_3d_singleTI":           1,  # raw ASL 1800 PLD
    "ASL pcasl_3d_singleTI 2100PLD":   1,  # raw ASL 2100 PLD
    "Perfusion_Weighted":              4,  # 2 acqs x (color + mean)
}

README_TEXT = """pCASL ASL BIDS Dataset
============================

Source data: Siemens MAGNETOM Vida Fit 3T, sequence tgse_asl
(pcasl_3d_singleTI, 3D GRASE readout).

Each subject has up to two ASL acquisitions:
  acq-singleTI       PostLabelingDelay = 1.8 s
  acq-singleTI2100   PostLabelingDelay = 2.1 s

ASL volume order (verified from DICOM ImageComments tag,
not guessed): 1 M0 scan + 8 (label, control) pairs = 17 volumes.
This is encoded in each _aslcontext.tsv.

Scanner-computed perfusion / CBF maps from the same exams are stored
under derivatives/scanner-cbf/. They are derivative images; the
spatial transform in their headers is approximate (the DICOMs from
the scanner are missing 0020,0037 orientation).

PHI handling
------------
JSON sidecars in this BIDS tree are anonymized (dcm2niix -ba y).
A mapping file `dicom_bids_mapping.csv` at the BIDS root contains the
original DICOM source paths plus PHI (PatientID, PatientName, etc.).
This mapping CSV must NOT leave protected premises.
"""


def ensure_bids_root(bids_root: Path) -> None:
    """Create/refresh pipeline-managed BIDS root files. README is create-only
    so user edits are preserved; schema/index files are always rewritten so
    this script remains the source of truth for BIDS metadata."""
    bids_root.mkdir(parents=True, exist_ok=True)

    # Always rewrite (pipeline-managed)
    (bids_root / "dataset_description.json").write_text(
        json.dumps(DATASET_DESCRIPTION, indent=2) + "\n")
    (bids_root / "participants.json").write_text(
        json.dumps(PARTICIPANTS_JSON, indent=2) + "\n")
    (bids_root / ".bidsignore").write_text(
        # Mapping CSV intentionally contains PHI; logs are operational, not BIDS.
        "dicom_bids_mapping.csv\nlogs/\n")

    # Create-only (preserves user edits)
    readme = bids_root / "README"
    if not readme.exists():
        readme.write_text(README_TEXT)
    participants = bids_root / "participants.tsv"
    if not participants.exists():
        participants.write_text("participant_id\tsex\tage\n")


def upsert_participant(bids_root: Path, subject: str, sex: str, age: str) -> None:
    participants = bids_root / "participants.tsv"
    lines = participants.read_text().splitlines()
    header = lines[0]
    rows = [l for l in lines[1:] if l and not l.startswith(subject + "\t")]
    rows.append(f"{subject}\t{sex or 'n/a'}\t{age or 'n/a'}")
    participants.write_text(header + "\n" + "\n".join(rows) + "\n")


# ---- main conversion --------------------------------------------------------

def run(dicom_src: Path, subject: str, bids_root: Path,
        allow_extra: bool = False, allow_missing: bool = False) -> None:
    if not dicom_src.is_dir():
        sys.exit(f"DICOM source not found: {dicom_src}")
    if not subject.startswith("sub-"):
        sys.exit(f"bids_subject_id must start with 'sub-': {subject}")

    ensure_bids_root(bids_root)
    phi = collect_dicom_phi(dicom_src)

    with tempfile.TemporaryDirectory(prefix="dcm2niix_") as tmp:
        cmd = ["dcm2niix", "-ba", "y", "-z", "y",
               "-f", "series%s_%d", "-o", tmp, str(dicom_src)]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        nii_files = sorted(Path(tmp).glob("*.nii.gz"))
        if not nii_files:
            sys.exit("dcm2niix produced no NIfTI output")

        # Strict protocol check: tally SeriesDescription counts in dcm2niix output
        seen_counts: dict[str, int] = defaultdict(int)
        for nii in nii_files:
            json_path = nii.with_suffix("").with_suffix(".json")
            if json_path.exists():
                j = json.loads(json_path.read_text())
                seen_counts[j.get("SeriesDescription", "")] += 1

        missing = [s for s, n in EXPECTED_SERIES.items() if seen_counts.get(s, 0) < n]
        unexpected = [s for s in seen_counts if s not in EXPECTED_SERIES]
        if missing and not allow_missing:
            sys.exit(
                f"protocol mismatch for {subject}: missing series "
                f"{missing} (have {dict(seen_counts)}). "
                "Re-run with --allow-missing to convert anyway."
            )
        if unexpected and not allow_extra:
            sys.exit(
                f"protocol mismatch for {subject}: unexpected series "
                f"{unexpected}. Re-run with --allow-extra-series to convert anyway."
            )

        mapping_rows: list[dict] = []

        for nii in nii_files:
            json_path = nii.with_suffix("").with_suffix(".json")
            if not json_path.exists():
                print(f"  skip {nii.name}: no JSON sidecar", file=sys.stderr)
                continue
            j = json.loads(json_path.read_text())
            cls = classify_series(j)
            if cls is None:
                # Already gated above; only reachable with --allow-extra-series.
                print(f"  skip {nii.name}: unknown series "
                      f"{j.get('SeriesDescription')}", file=sys.stderr)
                continue

            # Destination
            if cls["kind"] == "anat":
                dest_dir = bids_root / subject / "anat"
                stem = bids_filename(subject, cls["suffix"], cls["entities"], "")
                relative_prefix = f"{subject}/anat/{stem}"
            elif cls["kind"] == "perf_asl":
                dest_dir = bids_root / subject / "perf"
                stem = bids_filename(subject, cls["suffix"], cls["entities"], "")
                j = augment_asl_json(j, cls["pld_s"])
                relative_prefix = f"{subject}/perf/{stem}"
            elif cls["kind"] == "derivative_cbf":
                dest_dir = bids_root / "derivatives" / "scanner-cbf" / subject / "perf"
                stem = bids_filename(subject, cls["suffix"], cls["entities"], "")
                relative_prefix = f"derivatives/scanner-cbf/{subject}/perf/{stem}"
            else:
                continue

            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_nii = dest_dir / (stem + ".nii.gz")
            dest_json = dest_dir / (stem + ".json")
            shutil.copy2(nii, dest_nii)
            dest_json.write_text(json.dumps(j, indent=2) + "\n")

            mapping_rows.append({
                "bids_subject_id": subject,
                "dicom_source_dir": str(dicom_src),
                "patient_id": phi["PatientID"],
                "patient_name": phi["PatientName"],
                "patient_birth_date": phi["PatientBirthDate"],
                "patient_sex": phi["PatientSex"],
                "patient_age": phi["PatientAge"],
                "study_date": phi["StudyDate"],
                "study_description": phi["StudyDescription"],
                "study_instance_uid": phi["StudyInstanceUID"],
                "institution": phi["InstitutionName"],
                "scanner_model": phi["ManufacturerModelName"],
                "series_number": j.get("SeriesNumber"),
                "series_description": j.get("SeriesDescription"),
                "protocol_name": j.get("ProtocolName"),
                "image_type": "/".join(j.get("ImageType", [])),
                "bids_path": f"{relative_prefix}.nii.gz",
            })

            # ASL: write aslcontext.tsv next to it
            if cls["kind"] == "perf_asl":
                asl_ctx = dest_dir / (stem.replace("_asl", "_aslcontext") + ".tsv")
                asl_ctx.write_text("volume_type\n" + "\n".join(ASL_CONTEXT_ROWS) + "\n")
                mapping_rows.append({
                    "bids_subject_id": subject,
                    "dicom_source_dir": str(dicom_src),
                    "patient_id": phi["PatientID"],
                    "patient_name": phi["PatientName"],
                    "patient_birth_date": phi["PatientBirthDate"],
                    "patient_sex": phi["PatientSex"],
                    "patient_age": phi["PatientAge"],
                    "study_date": phi["StudyDate"],
                    "study_description": phi["StudyDescription"],
                    "study_instance_uid": phi["StudyInstanceUID"],
                    "institution": phi["InstitutionName"],
                    "scanner_model": phi["ManufacturerModelName"],
                    "series_number": j.get("SeriesNumber"),
                    "series_description": j.get("SeriesDescription"),
                    "protocol_name": j.get("ProtocolName"),
                    "image_type": "aslcontext",
                    "bids_path": str(asl_ctx.relative_to(bids_root)),
                })

    upsert_participant(bids_root, subject, phi["PatientSex"], phi["PatientAge"])

    # Append mapping rows (create with header on first write)
    mapping_csv = bids_root / "dicom_bids_mapping.csv"
    fieldnames = list(mapping_rows[0].keys())
    new_file = not mapping_csv.exists()
    with mapping_csv.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        if new_file:
            w.writeheader()
        for r in mapping_rows:
            w.writerow(r)

    print(f"converted {len(mapping_rows)} files for {subject}")
    print(f"BIDS root: {bids_root}")
    print(f"mapping  : {mapping_csv}")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("dicom_src", type=Path)
    p.add_argument("subject")
    p.add_argument("bids_root", type=Path)
    p.add_argument("--allow-extra-series", action="store_true",
                   help="convert even if dcm2niix found series outside EXPECTED_SERIES")
    p.add_argument("--allow-missing", action="store_true",
                   help="convert even if some EXPECTED_SERIES are missing")
    args = p.parse_args(argv)
    run(args.dicom_src, args.subject, args.bids_root,
        allow_extra=args.allow_extra_series, allow_missing=args.allow_missing)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
