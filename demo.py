"""Start the synthetic demo from any directory: python demo.py."""
import os
from pathlib import Path
import subprocess
import sys


def main():
    app_dir = Path(__file__).resolve().parent / "apps" / "offer-calendar"
    environment = os.environ.copy()
    environment["OFFER_CALENDAR_PREVIEW"] = "1"
    environment["DATABRICKS_APP_NAME"] = "offer-calendar-fiber"
    return subprocess.call(
        [sys.executable, "-m", "streamlit", "run", "app.py", *sys.argv[1:]],
        cwd=app_dir,
        env=environment,
    )


if __name__ == "__main__":
    raise SystemExit(main())
