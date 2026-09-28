# Pipeline runner for the home server: Python fetchers + R (worldfootballR).
# rocker/r-ver is Ubuntu with Posit Package Manager preconfigured, so R packages
# install as prebuilt binaries — no compiling httr/curl/xml2 against -dev libs
# (which is exactly what failed on the GitHub runner).
FROM rocker/r-ver:4

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-venv ca-certificates libcurl4 libxml2 libssl3t64 \
 && rm -rf /var/lib/apt/lists/*

RUN Rscript -e 'install.packages(c("worldfootballR","jsonlite"))' \
 && Rscript -e 'library(worldfootballR); library(jsonlite)'

COPY scripts/requirements.txt /tmp/requirements.txt
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

# Runs as the host user (see run.sh), so give scrapers a writable HOME for caches.
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUTF8=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp

WORKDIR /repo/scripts
CMD ["bash", "/repo/server/pipeline.sh"]
