import os
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
SITE_PACKAGES = BASE_DIR / "venv" / "Lib" / "site-packages"

if str(SITE_PACKAGES) not in sys.path:
    sys.path.insert(0, str(SITE_PACKAGES))

os.chdir(BASE_DIR)

import uvicorn


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, log_level="info")
