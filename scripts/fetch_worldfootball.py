"""Run the worldfootballR (R) cross-source read, if R is available.

worldfootballR is an R package, so this thin wrapper just invokes
fetch_worldfootball.R via Rscript and streams its output. If Rscript isn't on
PATH (or the R packages aren't installed) it skips cleanly, so the pipeline never
hard-depends on an R toolchain — it's a best-effort cross-validation layer.

Writes (via the R script):
  data/raw/worldfootball.json   name -> {bio, seasons:[...]}
"""
from __future__ import annotations

import glob
import shutil
import subprocess
import sys
from pathlib import Path

R_SCRIPT = Path(__file__).with_name("fetch_worldfootball.R")


def find_rscript() -> str | None:
    """Rscript on PATH, else the newest install under the usual Windows dirs."""
    on_path = shutil.which("Rscript") or shutil.which("Rscript.exe")
    if on_path:
        return on_path
    patterns = [
        r"C:\Program Files\R\*\bin\Rscript.exe",
        r"C:\Program Files\R\*\bin\x64\Rscript.exe",
    ]
    hits = sorted(p for pat in patterns for p in glob.glob(pat))
    return hits[-1] if hits else None


def main() -> None:
    rscript = find_rscript()
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
