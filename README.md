# ASL-AI

3D pCASL pipeline: **DICOM → BIDS → FreeSurfer → regional stats → asymmetry index**.

`AI = (Left − Right) / (Left + Right)` per matched aparc+aseg region pair.

## Requirements

- Python 3.9+, `dcm2niix`, Apptainer (or host FreeSurfer 7.x)
- FreeSurfer license file (`FS_LICENSE`)
- SLURM cluster access for batch runs

## CLI

```bash
./ASL install    # deps + config.local.env + subjects.tsv
./ASL start      # submit jobs
./ASL check      # queue + subject progress
./ASL logs       # latest pipeline log
./ASL logs sub-001   # follow one subject
```

## Setup

1. `./ASL install`
2. Edit `config.local.env` — set `FS_LICENSE`
3. Edit `subjects.tsv` — tab-separated `<dicom_dir>  <sub_id>`

Pull the FreeSurfer container once (if no host install):

```bash
sbatch slurm/pull_freesurfer.sh
```

## Outputs

| Path | Content |
|------|---------|
| `Data_ASL/` | BIDS dataset |
| `freesurfer_subjects/` | recon-all + registration |
| `Data_ASL/derivatives/asl-ai/<sub>/` | Per-subject AI CSVs (both PLDs) |

Logs: `Data_ASL/logs/<sub>_pipeline.log`

## Clone

```bash
git clone git@github.com:phindagijimana/ASL-AI.git
cd ASL-AI
git remote add origin git@github.com:phindagijimana/ASL-AI.git
git branch -M main
git push -u origin main
```
