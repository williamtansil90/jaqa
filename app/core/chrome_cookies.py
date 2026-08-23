from __future__ import annotations

import base64
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

CookieDbNames = ("Network/Cookies", "Cookies")

FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
SE_BACKUP_NAME = "SeBackupPrivilege"
SE_PRIVILEGE_ENABLED = 0x00000002
TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_QUERY = 0x0008


def _enable_backup_privilege() -> bool:
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class LUID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]

    class TOKEN_PRIVILEGES(ctypes.Structure):
        _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", LUID_AND_ATTRIBUTES * 1)]

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(token)
    ):
        return False

    luid = LUID()
    if not advapi32.LookupPrivilegeValueW(None, SE_BACKUP_NAME, ctypes.byref(luid)):
        kernel32.CloseHandle(token)
        return False

    privileges = TOKEN_PRIVILEGES()
    privileges.PrivilegeCount = 1
    privileges.Privileges[0].Luid = luid
    privileges.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED
    if not advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(privileges), 0, None, None):
        kernel32.CloseHandle(token)
        return False
    kernel32.CloseHandle(token)
    return True


def _read_locked_file_windows(path: Path) -> bytes:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    share = FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE
    attempts = (
        (GENERIC_READ, share, 0),
        (GENERIC_READ, share, FILE_FLAG_BACKUP_SEMANTICS),
    )
    if _enable_backup_privilege():
        attempts = (
            (GENERIC_READ, share, FILE_FLAG_BACKUP_SEMANTICS),
            (GENERIC_READ, share, 0),
        )

    last_error: Exception | None = None
    for access, share_mode, flags in attempts:
        handle = kernel32.CreateFileW(str(path), access, share_mode, None, OPEN_EXISTING, flags, None)
        if handle in (-1, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
            last_error = ctypes.WinError(ctypes.get_last_error())
            continue

        data = bytearray()
        try:
            buffer = ctypes.create_string_buffer(65536)
            read = wintypes.DWORD()
            while True:
                ok = kernel32.ReadFile(handle, buffer, 65536, ctypes.byref(read), None)
                if not ok:
                    raise ctypes.WinError(ctypes.get_last_error())
                if read.value == 0:
                    break
                data.extend(buffer.raw[: read.value])
        finally:
            kernel32.CloseHandle(handle)
        return bytes(data)

    raise last_error or OSError(f"Tidak bisa membaca file: {path}")


def _copy_cookie_db_to_temp(source: Path) -> Path:
    temp_db = Path(tempfile.mktemp(suffix=".jaqa-cookies"))
    try:
        shutil.copy2(source, temp_db)
        return temp_db
    except OSError:
        pass
    if sys.platform == "win32":
        temp_db.write_bytes(_read_locked_file_windows(source))
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = source.parent / f"{source.name}{suffix}"
            if sidecar.exists():
                try:
                    (temp_db.parent / f"{temp_db.name}{suffix}").write_bytes(_read_locked_file_windows(sidecar))
                except OSError:
                    pass
        return temp_db
    raise RuntimeError(f"Tidak bisa menyalin database cookies:\n{source}")


def _dpapi_decrypt(data: bytes) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError("DPAPI hanya tersedia di Windows.")
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    blob_in = DATA_BLOB(len(data), ctypes.create_string_buffer(data, len(data)))
    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise RuntimeError("DPAPI decrypt gagal.")

    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _aes_gcm_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, tag: bytes) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError("AES-GCM via BCrypt hanya tersedia di Windows.")
    import ctypes
    from ctypes import wintypes

    bcrypt = ctypes.WinDLL("bcrypt")
    BCRYPT_AES_ALGORITHM = "AES"
    BCRYPT_CHAINING_MODE = "ChainingMode"
    BCRYPT_CHAIN_MODE_GCM = "ChainingModeGCM"
    BCRYPT_AUTH_MODE_CHAIN_CALLS_FLAG = 0x00000001
    STATUS_SUCCESS = 0

    class BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.ULONG),
            ("dwInfoVersion", wintypes.ULONG),
            ("pbNonce", ctypes.c_void_p),
            ("cbNonce", wintypes.ULONG),
            ("pbAuthData", ctypes.c_void_p),
            ("cbAuthData", wintypes.ULONG),
            ("pbTag", ctypes.c_void_p),
            ("cbTag", wintypes.ULONG),
            ("pbMacContext", ctypes.c_void_p),
            ("cbMacContext", wintypes.ULONG),
            ("cbAAD", wintypes.ULONG),
            ("cbData", wintypes.ULONGLONG),
            ("dwFlags", wintypes.ULONG),
        ]

    def _check(status: int, msg: str) -> None:
        if status != STATUS_SUCCESS:
            raise RuntimeError(f"{msg} (status=0x{status & 0xFFFFFFFF:08X})")

    alg_handle = wintypes.HANDLE()
    _check(
        bcrypt.BCryptOpenAlgorithmProvider(
            ctypes.byref(alg_handle), BCRYPT_AES_ALGORITHM, None, BCRYPT_AUTH_MODE_CHAIN_CALLS_FLAG
        ),
        "BCryptOpenAlgorithmProvider gagal",
    )

    key_handle = wintypes.HANDLE()
    try:
        mode = ctypes.create_unicode_buffer(BCRYPT_CHAIN_MODE_GCM)
        _check(
            bcrypt.BCryptSetProperty(
                alg_handle,
                BCRYPT_CHAINING_MODE,
                ctypes.cast(mode, ctypes.c_void_p),
                len(BCRYPT_CHAIN_MODE_GCM),
                0,
            ),
            "BCryptSetProperty gagal",
        )

        obj_len = wintypes.ULONG()
        data_len = wintypes.ULONG()
        _check(
            bcrypt.BCryptGetProperty(
                alg_handle, "ObjectLength", ctypes.byref(obj_len), 4, ctypes.byref(data_len), 0
            ),
            "BCryptGetProperty ObjectLength gagal",
        )
        key_object = (ctypes.c_char * obj_len.value)()
        _check(
            bcrypt.BCryptGenerateSymmetricKey(
                alg_handle,
                ctypes.byref(key_handle),
                key_object,
                obj_len,
                ctypes.create_string_buffer(key, len(key)),
                len(key),
                0,
            ),
            "BCryptGenerateSymmetricKey gagal",
        )

        auth_info = BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO()
        auth_info.cbSize = ctypes.sizeof(BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO)
        auth_info.dwInfoVersion = 1
        auth_info.pbNonce = ctypes.cast(ctypes.create_string_buffer(nonce, len(nonce)), ctypes.c_void_p)
        auth_info.cbNonce = len(nonce)
        auth_info.pbTag = ctypes.cast(ctypes.create_string_buffer(tag, len(tag)), ctypes.c_void_p)
        auth_info.cbTag = len(tag)

        plain = (ctypes.c_char * len(ciphertext))()
        plain_len = wintypes.ULONG()
        _check(
            bcrypt.BCryptDecrypt(
                key_handle,
                ctypes.create_string_buffer(ciphertext, len(ciphertext)),
                len(ciphertext),
                ctypes.byref(auth_info),
                None,
                0,
                plain,
                len(ciphertext),
                ctypes.byref(plain_len),
                0,
            ),
            "BCryptDecrypt gagal",
        )
        return plain.raw[: plain_len.value]
    finally:
        if key_handle.value:
            bcrypt.BCryptDestroyKey(key_handle)
        bcrypt.BCryptCloseAlgorithmProvider(alg_handle, 0)


def _chrome_aes_key(local_state: Path) -> bytes:
    payload = json.loads(local_state.read_text(encoding="utf-8"))
    encoded = base64.b64decode(payload["os_crypt"]["encrypted_key"])
    return _dpapi_decrypt(encoded[5:])


def _decrypt_cookie_value(raw: bytes, key: bytes) -> str:
    if not raw:
        return ""
    if raw[:3] in {b"v10", b"v11"}:
        nonce = raw[3:15]
        payload = raw[15:]
        tag = payload[-16:]
        ciphertext = payload[:-16]
        return _aes_gcm_decrypt(key, nonce, ciphertext, tag).decode("utf-8", errors="replace")
    return _dpapi_decrypt(raw).decode("utf-8", errors="replace")


def _chrome_expires_to_playwright(expires_utc: int) -> float:
    if not expires_utc:
        return -1
    return (expires_utc / 1_000_000) - 11_644_473_600


def _same_site_label(value: int) -> str:
    if value == 1:
        return "Lax"
    if value == 2:
        return "Strict"
    if value == 0:
        return "None"
    return "Lax"


def _open_cookie_db(db_path: Path) -> sqlite3.Connection:
    uris = [
        f"file:{db_path.resolve().as_posix()}?mode=ro&immutable=1",
        f"file:{db_path.resolve().as_posix()}?mode=ro&nolock=1",
        f"file:{db_path.resolve().as_posix()}?mode=ro",
    ]
    last_error: Exception | None = None
    for uri in uris:
        try:
            return sqlite3.connect(uri, uri=True)
        except sqlite3.Error as exc:
            last_error = exc
    raise RuntimeError(f"Tidak bisa membuka database cookies Chrome: {last_error}")


def _backup_cookie_db(source: Path) -> Path:
    temp_db = _copy_cookie_db_to_temp(source)
    src_conn = None
    dst_conn = None
    out_db = Path(tempfile.mktemp(suffix=".jaqa-cookies-clean"))
    try:
        src_conn = sqlite3.connect(temp_db)
        dst_conn = sqlite3.connect(out_db)
        src_conn.backup(dst_conn)
        dst_conn.commit()
        return out_db
    except sqlite3.Error:
        return temp_db
    finally:
        if src_conn is not None:
            src_conn.close()
        if dst_conn is not None:
            dst_conn.close()
        if out_db.exists() and temp_db.exists() and out_db != temp_db:
            temp_db.unlink(missing_ok=True)


def read_chrome_cookies(user_data: Path, profile_name: str = "Default") -> list[dict[str, Any]]:
    profile_dir = user_data / profile_name
    local_state = user_data / "Local State"
    if not local_state.exists():
        raise FileNotFoundError(f"File Local State tidak ditemukan:\n{local_state}")

    db_path = next((profile_dir / rel for rel in CookieDbNames if (profile_dir / rel).exists()), None)
    if db_path is None:
        raise FileNotFoundError(f"Database cookies tidak ditemukan di profile:\n{profile_dir}")

    key = _chrome_aes_key(local_state)
    temp_db: Path | None = None
    conn: sqlite3.Connection | None = None
    try:
        temp_db = _backup_cookie_db(db_path)
        conn = sqlite3.connect(temp_db)

        rows = conn.execute(
            "SELECT host_key, name, encrypted_value, path, expires_utc, is_secure, is_httponly, samesite FROM cookies"
        ).fetchall()

        cookies: list[dict[str, Any]] = []
        for host, name, encrypted, path, expires_utc, secure, httponly, samesite in rows:
            if not name:
                continue
            try:
                value = _decrypt_cookie_value(encrypted or b"", key)
            except Exception:
                continue
            cookies.append(
                {
                    "name": name,
                    "value": value,
                    "domain": host,
                    "path": path or "/",
                    "expires": _chrome_expires_to_playwright(int(expires_utc or 0)),
                    "httpOnly": bool(httponly),
                    "secure": bool(secure),
                    "sameSite": _same_site_label(int(samesite if samesite is not None else -1)),
                }
            )
        if not cookies:
            raise RuntimeError("Database cookies terbaca, tetapi tidak ada cookie yang bisa didekripsi.")
        return cookies
    finally:
        if conn is not None:
            conn.close()
        if temp_db is not None and temp_db.exists():
            temp_db.unlink(missing_ok=True)
