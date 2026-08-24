from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.core.browser_setup import apply_env, BROWSER_ARGS, CONTEXT_KWARGS, new_browser_context
from app.core.chrome_cookies import _read_locked_file_windows, read_chrome_cookies

DEFAULT_CDP_URL = "http://127.0.0.1:9222"
DEFAULT_CDP_PORT = 9222
DEFAULT_CHROME_PROFILE = Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data" / "Default"
CHROME_EXE_CANDIDATES = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "Application" / "chrome.exe",
)

ProfileCopyPaths = (
    "Cookies",
    "Network/Cookies",
    "Preferences",
    "Local Storage",
    "Session Storage",
    "IndexedDB",
)

CookieDbNames = ("Network/Cookies", "Cookies")


@dataclass
class BrowserImportSource:
    mode: Literal["profile", "cdp"]
    value: str
    profile_name: str = "Default"


@dataclass
class ProfileStageResult:
    root: Path
    cookies_ready: bool
    session_ready: bool
    warnings: list[str]


def is_chrome_running() -> bool:
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/NH"],
                capture_output=True,
                text=True,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return "chrome.exe" in result.stdout.lower()
        except OSError:
            return False
    try:
        result = subprocess.run(["pgrep", "-x", "chrome"], capture_output=True, check=False)
        return result.returncode == 0
    except OSError:
        return False


def find_chrome_executable() -> Path | None:
    for candidate in CHROME_EXE_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def cdp_endpoint_available(cdp_url: str = DEFAULT_CDP_URL) -> bool:
    try:
        with urllib.request.urlopen(f"{cdp_url.rstrip('/')}/json/version", timeout=1.5) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def launch_chrome_with_cdp(
    user_data: Path,
    profile_name: str = "Default",
    port: int = DEFAULT_CDP_PORT,
) -> Path:
    chrome = find_chrome_executable()
    if chrome is None:
        raise FileNotFoundError("chrome.exe tidak ditemukan. Install Google Chrome terlebih dahulu.")

    profile_args = [
        str(chrome),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data}",
        f"--profile-directory={profile_name}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    args = profile_args + [flag for flag in BROWSER_ARGS if flag not in {"--start-maximized"}]
    subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0),
    )
    return chrome


def normalize_chrome_profile_path(path: str | Path) -> tuple[Path, str]:
    target = Path(path).expanduser()
    if not target.exists():
        raise FileNotFoundError(f"Path profile tidak ditemukan:\n{target}")

    resolved = target.resolve()
    if resolved.name.lower() == "default":
        user_data = resolved.parent
        if not (user_data / "Local State").exists() and (user_data.parent / "Local State").exists():
            user_data = user_data.parent
        return user_data, "Default"

    if (resolved / "Local State").exists() and (resolved / "Default").exists():
        return resolved, "Default"

    if resolved.name.lower() == "user data" or (resolved / "Local State").exists():
        profile = "Default"
        if not (resolved / profile).exists():
            raise FileNotFoundError(f"Folder profile '{profile}' tidak ditemukan di:\n{resolved}")
        return resolved, profile

    raise FileNotFoundError(
        "Path profile Chrome tidak dikenali.\n"
        "Contoh valid:\n"
        r"C:\Users\<nama>\AppData\Local\Google\Chrome\User Data\Default"
    )


def _backup_sqlite(source: Path, dest: Path) -> bool:
    if not source.exists():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()

    for uri in (
        f"file:{source.as_posix()}?mode=ro&immutable=1",
        f"file:{source.as_posix()}?mode=ro&nolock=1",
        f"file:{source.as_posix()}?mode=ro",
    ):
        src_conn = None
        dst_conn = None
        try:
            src_conn = sqlite3.connect(uri, uri=True)
            dst_conn = sqlite3.connect(dest)
            src_conn.backup(dst_conn)
            dst_conn.commit()
            return True
        except sqlite3.Error:
            continue
        finally:
            if src_conn is not None:
                src_conn.close()
            if dst_conn is not None:
                dst_conn.close()
    return False


def _copy_profile_item(source: Path, dest: Path) -> bool:
    if not source.exists():
        return False
    if source.is_dir():
        try:
            shutil.copytree(source, dest, dirs_exist_ok=True, ignore_dangling_symlinks=True)
            return True
        except OSError:
            if sys.platform == "win32":
                try:
                    dest.mkdir(parents=True, exist_ok=True)
                    for child in source.rglob("*"):
                        rel = child.relative_to(source)
                        target = dest / rel
                        if child.is_dir():
                            target.mkdir(parents=True, exist_ok=True)
                            continue
                        target.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            shutil.copy2(child, target)
                        except OSError:
                            _copy_profile_item(child, target)
                    return any(dest.iterdir())
                except OSError:
                    return False
            return False

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source, dest)
        return True
    except OSError:
        if source.name in {"Cookies", "Cookies-journal"} or "Cookies" in source.parts:
            return _backup_sqlite(source, dest)
        if sys.platform == "win32":
            try:
                dest.write_bytes(_read_locked_file_windows(source))
                return True
            except OSError:
                return False
        return False


def _ensure_cookie_db(src_profile: Path, dest_profile: Path) -> bool:
    for rel in CookieDbNames:
        src = src_profile / rel
        dst = dest_profile / rel
        if _copy_profile_item(src, dst):
            return True
        if _backup_sqlite(src, dst):
            return True
    return False


def _stage_chrome_profile(user_data: Path, profile_name: str) -> ProfileStageResult:
    staging_root = Path(tempfile.mkdtemp(prefix="jaqa-chrome-profile-"))
    warnings: list[str] = []

    local_state = user_data / "Local State"
    if local_state.exists():
        if not _copy_profile_item(local_state, staging_root / "Local State"):
            warnings.append("Local State tidak bisa disalin; decrypt cookies mungkin gagal.")

    src_profile = user_data / profile_name
    dest_profile = staging_root / profile_name
    dest_profile.mkdir(parents=True, exist_ok=True)

    copied = 0
    session_paths = ("Local Storage", "Session Storage", "IndexedDB")
    session_ok = True
    for rel in ProfileCopyPaths:
        src = src_profile / rel
        dst = dest_profile / rel
        if not src.exists():
            continue
        if _copy_profile_item(src, dst):
            copied += 1
            continue
        if rel in CookieDbNames:
            continue
        if rel in session_paths:
            session_ok = False
            warnings.append(f"'{rel}' sedang dipakai Chrome; dilewati.")
            continue
        warnings.append(f"'{rel}' tidak bisa disalin.")

    cookies_ready = _ensure_cookie_db(src_profile, dest_profile)

    if copied == 0 and not cookies_ready and not session_ok:
        raise RuntimeError(
            "Tidak ada data profile yang bisa dibaca.\n"
            "Pastikan path benar."
        )

    if not session_ok:
        warnings.append("Session localStorage mungkin tidak lengkap karena Chrome masih berjalan.")

    return ProfileStageResult(
        root=staging_root,
        cookies_ready=cookies_ready,
        session_ready=session_ok,
        warnings=warnings,
    )


def _extract_from_profile(user_data: Path, profile_name: str, *, cookies_only: bool) -> list[dict[str, Any]] | dict[str, Any]:
    apply_env()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = None
        try:
            for channel in ("chrome", "msedge", None):
                try:
                    kwargs: dict[str, Any] = {
                        "user_data_dir": str(user_data),
                        "headless": True,
                        "ignore_https_errors": True,
                        "args": [
                            f"--profile-directory={profile_name}",
                            *BROWSER_ARGS,
                            "--no-first-run",
                            "--no-default-browser-check",
                        ],
                    }
                    if channel:
                        kwargs["channel"] = channel
                    context = playwright.chromium.launch_persistent_context(**kwargs)
                    break
                except Exception:
                    context = None
                    continue
            if context is None:
                raise RuntimeError("Tidak bisa membuka profile Chrome untuk membaca cookies/session.")

            if cookies_only:
                return context.cookies()
            return context.storage_state()
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass


def _cleanup_staged_user_data(staging_root: Path) -> None:
    try:
        shutil.rmtree(staging_root, ignore_errors=True)
    except OSError:
        pass


def _profile_import_failure(kind: str = "Cookies") -> RuntimeError:
    lines = [f"{kind} Chrome tidak bisa dibaca."]
    if is_chrome_running():
        lines.append("Chrome sedang berjalan dan mengunci file cookies/session.")
    if cdp_endpoint_available():
        lines.append("CDP aktif di http://127.0.0.1:9222 — pilih mode CDP URL lalu import lagi.")
    else:
        lines.extend(
            [
                "Pilihan:",
                "1. Tutup semua jendela Chrome, lalu import lagi dari profile path.",
                "2. Tutup Chrome, jalankan ulang dengan remote debugging, lalu pilih CDP URL:",
                r'   "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222',
            ]
        )
    return RuntimeError("\n".join(lines))


def _try_cdp_cookie_fallback(warnings: list[str]) -> list[dict[str, Any]] | None:
    if not cdp_endpoint_available():
        return None
    try:
        cookies = fetch_cookies_from_browser()
        warnings.append("Profile terkunci; cookies diambil otomatis via CDP (127.0.0.1:9222).")
        return cookies
    except Exception as exc:
        warnings.append(f"CDP fallback gagal: {exc}")
        return None


def _try_cdp_session_fallback(warnings: list[str]) -> dict[str, Any] | None:
    if not cdp_endpoint_available():
        return None
    try:
        state = fetch_storage_state_from_browser()
        warnings.append("Profile terkunci; session diambil otomatis via CDP (127.0.0.1:9222).")
        return state
    except Exception as exc:
        warnings.append(f"CDP fallback gagal: {exc}")
        return None


def fetch_cookies_from_profile(profile_path: str | Path) -> tuple[list[dict[str, Any]], list[str]]:
    user_data, profile_name = normalize_chrome_profile_path(profile_path)
    warnings: list[str] = []
    try:
        cookies = read_chrome_cookies(user_data, profile_name)
        if cookies:
            return cookies, warnings
    except Exception as exc:
        warnings.append(f"Baca langsung gagal: {exc}")

    staged = _stage_chrome_profile(user_data, profile_name)
    try:
        if staged.cookies_ready:
            result = _extract_from_profile(staged.root, profile_name, cookies_only=True)
            return result, warnings + staged.warnings  # type: ignore[return-value]
    finally:
        _cleanup_staged_user_data(staged.root)

    cdp_cookies = _try_cdp_cookie_fallback(warnings)
    if cdp_cookies:
        return cdp_cookies, warnings

    raise _profile_import_failure("Cookies")


def fetch_storage_state_from_profile(profile_path: str | Path) -> tuple[dict[str, Any], list[str]]:
    user_data, profile_name = normalize_chrome_profile_path(profile_path)
    warnings: list[str] = []
    cookies: list[dict[str, Any]] = []
    try:
        cookies = read_chrome_cookies(user_data, profile_name)
    except Exception as exc:
        warnings.append(f"Cookies langsung gagal: {exc}")

    staged = _stage_chrome_profile(user_data, profile_name)
    try:
        if staged.cookies_ready or staged.session_ready:
            try:
                state = _extract_from_profile(staged.root, profile_name, cookies_only=False)
                if cookies and not state.get("cookies"):
                    state["cookies"] = cookies
                return state, warnings + staged.warnings
            except Exception as exc:
                warnings.append(f"Session Playwright gagal: {exc}")
    finally:
        _cleanup_staged_user_data(staged.root)

    if cookies:
        warnings.append("Hanya cookies yang berhasil diimport (localStorage tidak tersedia).")
        return {"cookies": cookies, "origins": []}, warnings

    cdp_state = _try_cdp_session_fallback(warnings)
    if cdp_state:
        return cdp_state, warnings

    raise _profile_import_failure("Session")


def _pick_context(browser) -> Any:
    if browser.contexts:
        return browser.contexts[0]
    return new_browser_context(browser)


def fetch_cookies_from_browser(cdp_url: str = DEFAULT_CDP_URL) -> list[dict[str, Any]]:
    apply_env()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(cdp_url)
        try:
            context = _pick_context(browser)
            return context.cookies()
        finally:
            browser.close()


def fetch_storage_state_from_browser(cdp_url: str = DEFAULT_CDP_URL) -> dict[str, Any]:
    apply_env()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(cdp_url)
        try:
            context = _pick_context(browser)
            return context.storage_state()
        finally:
            browser.close()


def fetch_cookies(source: BrowserImportSource) -> tuple[list[dict[str, Any]], list[str]]:
    if source.mode == "profile":
        return fetch_cookies_from_profile(source.value)
    return fetch_cookies_from_browser(source.value), []


def fetch_storage_state(source: BrowserImportSource) -> tuple[dict[str, Any], list[str]]:
    if source.mode == "profile":
        return fetch_storage_state_from_profile(source.value)
    return fetch_storage_state_from_browser(source.value), []


def warnings_text(warnings: list[str]) -> str:
    if not warnings:
        return ""
    return "  •  " + "  •  ".join(warnings)
