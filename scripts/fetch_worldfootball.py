"""Run the worldfootballR (R) cross-source read, if R is available.

worldfootballR is an R package, so this thin wrapper just invokes
fetch_worldfootball.R via Rscript and streams its output. If Rscript isn't on
PATH (or the R packages aren't installed) it skips cleanly, so the pipeline never
hard-depends on an R toolchain — it's a best-effort cross-validation layer.

Writes (via the R script):
  data/raw/worldfootball.json   name -> {bio, seasons:[...]}
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

R_SCRIPT = Path(__file__).with_name("fetch_worldfootball.R")


def main() -> None:
    rscript = shutil.which("Rscript")
    if not rscript:
        print("Rscript not found on PATH — skipping worldfootballR cross-read.")
        print("  Install R + `install.packages(c('worldfootballR','jsonlite'))` to enable it.")
        sys.exit(0)

    print(f"Running {R_SCRIPT.name} via {rscript} ...")
    # cwd = scripts/ so the R script's relative ../data/raw paths resolve.
    result = subprocess.run([rscript, str(R_SCRIPT)], cwd=str(R_SCRIPT.parent))
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
