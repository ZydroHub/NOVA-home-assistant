#!/usr/bin/env python3
"""Compatibility launcher for the backend.

Preferred startup is still direct:
    python app.py
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
APP_FILE = ROOT / "app.py"
REQUIREMENTS_FILE = ROOT / "requirements.txt"

logger = logging.getLogger("run_backend")


def configure_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch NOVA backend safely.")
    parser.add_argument("--debug", action="store_true", help="Enable verbose launcher logs")
    return parser.parse_args()


def check_required_modules() -> list[str]:
    required = [
        "fastapi",
        "uvicorn",
        "psutil",
        "numpy",
        "scipy",
        "pyaudio",
        "faster_whisper",
        "vosk",
        "huggingface_hub",
        "llama_cpp",
    ]
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    return missing


def install_requirements() -> bool:
    if not REQUIREMENTS_FILE.exists():
        logger.error("requirements.txt not found at %s", REQUIREMENTS_FILE)
        return False
    try:
        logger.info("Installing dependencies from requirements.txt...")
        subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], cwd=str(ROOT), check=True)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--upgrade",
                "setuptools",
                "wheel",
                "ninja",
                "cmake",
                "scikit-build-core",
            ],
            cwd=str(ROOT),
            check=True,
        )
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-build-isolation", "-r", str(REQUIREMENTS_FILE)],
            cwd=str(ROOT),
            check=True,
        )
        return True
    except subprocess.CalledProcessError as exc:
        logger.error("Dependency installation failed with exit code %s", exc.returncode)
        return False


def check_linux_build_tools() -> bool:
    """Return True when required build tools are present on Linux."""
    if sys.platform.startswith("linux"):
        required_tools = ["ninja", "cmake", "gcc", "g++"]
        missing_tools = [tool for tool in required_tools if shutil.which(tool) is None]
        if missing_tools:
            logger.error("Missing Linux build tools: %s", ", ".join(missing_tools))
            if shutil.which("apt-get"):
                hint = "sudo apt update && sudo apt install -y ninja-build cmake build-essential python3-dev"
            elif shutil.which("dnf"):
                hint = "sudo dnf install -y ninja-build cmake gcc gcc-c++ python3-devel"
            elif shutil.which("pacman"):
                hint = "sudo pacman -S --needed ninja cmake base-devel python"
            else:
                hint = "install ninja, cmake, gcc, g++, and Python development headers with your distro package manager"
            logger.error("Install with: %s", hint)
            return False
    return True


def preflight_checks() -> int:
    if not APP_FILE.exists():
        logger.error("Missing app entrypoint: %s", APP_FILE)
        return 1

    missing = check_required_modules()
    if missing:
        logger.warning("Missing Python packages: %s", ", ".join(missing))
        if "llama_cpp" in missing and not check_linux_build_tools():
            return 2
        if not install_requirements():
            logger.error("Install dependencies manually with: %s -m pip install -r requirements.txt", sys.executable)
            return 2
        missing_after_install = check_required_modules()
        if missing_after_install:
            logger.error("Still missing Python packages after install: %s", ", ".join(missing_after_install))
            return 3

    logger.debug("Preflight checks passed. Using Python: %s", sys.executable)
    return 0


def main() -> int:
    args = parse_args()
    configure_logging(debug=args.debug)

    logger.info("run_backend.py wrapper: launching app.py")
    preflight_code = preflight_checks()
    if preflight_code != 0:
        return preflight_code

    try:
        cmd = [sys.executable, str(APP_FILE)]
        logger.debug("Command: %s", " ".join(cmd))
        subprocess.run(cmd, cwd=str(ROOT), check=True)
        return 0
    except KeyboardInterrupt:
        logger.info("Launcher interrupted by user (Ctrl+C).")
        return 130
    except subprocess.CalledProcessError as exc:
        logger.error("Backend process exited with code %s", exc.returncode)
        logger.error("Failed to launch app.py: %s", exc)
        return exc.returncode or 1
    except Exception as exc:
        logger.exception("Unexpected launcher error: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
