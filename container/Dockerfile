# ASL-AI compute layer: extract_asl_derivatives, compute_asymmetry, clinical PDF reports.
# Pipeline scripts are bind-mounted at runtime (see compute_setup.sh).

FROM python:3.11-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /asl-ai

COPY requirements-compute.txt /tmp/requirements-compute.txt
RUN pip install --no-cache-dir -r /tmp/requirements-compute.txt \
    && rm /tmp/requirements-compute.txt

ENV PYTHONPATH=/asl-ai
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python3"]
