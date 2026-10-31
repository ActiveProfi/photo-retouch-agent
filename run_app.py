"""Запуск приложения: python run_app.py"""

import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    app = root / "app.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app)], check=False)


if __name__ == "__main__":
    main()
