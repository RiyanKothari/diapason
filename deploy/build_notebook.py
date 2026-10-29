"""Build deploy/evon_kaggle.ipynb from deploy/evon_kaggle.py ('# %%' percent format, no extra dependencies).

    python deploy/build_notebook.py            # after editing evon_kaggle.py, then re-import the .ipynb in Kaggle
"""
import json
import re
import sys
from pathlib import Path

here = Path(__file__).parent
src = Path(sys.argv[1]) if len(sys.argv) > 1 else here / "evon_kaggle.py"
dst = Path(sys.argv[2]) if len(sys.argv) > 2 else here / "evon_kaggle.ipynb"

cells = []
for chunk in re.split(r"^# %%", src.read_text(encoding="utf-8"), flags=re.M)[1:]:
    header, _, body = chunk.partition("\n")
    if header.strip().startswith("[markdown]"):
        lines = [re.sub(r"^# ?", "", l) for l in body.strip("\n").splitlines()]
        cells.append({"cell_type": "markdown", "metadata": {}, "source": "\n".join(lines)})
    else:
        title = header.strip()
        code = (f"# {title}\n" if title else "") + body.strip("\n")
        compile(code, f"{src.name} cell {len(cells)}", "exec")      # fail here, not 15 minutes into a GPU session
        cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": code})

nb = {"nbformat": 4, "nbformat_minor": 5, "cells": cells,
      "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
                   "language_info": {"name": "python"},
                   # Kaggle reads these on import; still confirm GPU T4 x2 + Internet On in Session options.
                   "kaggle": {"accelerator": "nvidiaTeslaT4", "isGpuEnabled": True, "isInternetEnabled": True,
                              "language": "python", "sourceType": "notebook", "dataSources": []}}}
dst.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"{dst}: {len(cells)} cells")
