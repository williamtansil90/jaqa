from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def browsers_path() -> Path:
    path = Path.home() / "AppData" / "Local" / "JAQA" / "ms-playwright"
    path.mkdir(parents=True, exist_ok=True)
    return path


def apply_env() -> None:
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browsers_path()))


def chrome_available() -> bool:
    program = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    program_x86 = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
    candidates = [
        program / "Google" / "Chrome" / "Application" / "chrome.exe",
        program_x86 / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "Application" / "chrome.exe",
        program / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ]
    return any(path.exists() for path in candidates)


def chromium_ready() -> bool:
    if chrome_available():
        return True
    apply_env()
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            exe = playwright.chromium.executable_path
            return bool(exe and Path(exe).exists())
    except Exception:
        return False


def install_chromium() -> None:
    apply_env()
    from playwright._impl._driver import compute_driver_executable, get_driver_env

    driver = compute_driver_executable()
    if isinstance(driver, tuple):
        cmd = [str(part) for part in driver] + ["install", "chromium"]
    else:
        cmd = [str(driver), "install", "chromium"]
    subprocess.check_call(cmd, env=get_driver_env())


BROWSER_ARGS = [
    "--start-maximized",
    "--disable-dev-shm-usage",
    "--ignore-certificate-errors",
    "--allow-insecure-localhost",
]

CONTEXT_KWARGS = {
    "no_viewport": True,
    "ignore_https_errors": True,
}


def launch_browser(playwright):
    apply_env()
    args = list(BROWSER_ARGS)
    for channel in ("chrome", "msedge"):
        try:
            return playwright.chromium.launch(channel=channel, headless=False, args=args)
        except Exception:
            continue
    return playwright.chromium.launch(headless=False, args=args)


def new_browser_context(browser, **extra):
    return browser.new_context(**CONTEXT_KWARGS, **extra)


def python_or_frozen() -> str:
    return sys.executable
