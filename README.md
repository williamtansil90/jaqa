# JAQA — Jalin Automate QA

Aplikasi desktop SIT otomatis (Python + Playwright + PyInstaller).

Rekam langkah pengguna di browser, tandai **Expected Result** pada elemen, jalankan ulang test case, lalu nilai **OK** (hijau) / **NOK** (merah + catatan). Suite bisa diekspor/impor JSON; hasil run bisa diekspor Excel atau PDF.

## Alur kerja

1. **Tambah TC** — isi `NO. TC`, Deskripsi, Aplikasi, URL, Username, Password, Expected Result.
2. Pilih baris, klik **RECORD**. Browser terbuka ke URL. Lakukan langkah uji (klik, isi, pilih, Enter).
3. Saat merekam, klik **EXPECTED RESULT**, lalu klik elemen di halaman dan isi nilai yang diharapkan. Bisa berulang (beberapa expected per TC).
4. Klik **RECORD** lagi untuk berhenti. Rekaman + expected tersimpan otomatis.
5. Jalankan:
   - **Single Run**
   - **Run Until**
   - **Run All**
6. Setiap expected dinilai. OK hijau, NOK merah beserta alasan di kolom Catatan.
7. **Ekspor JSON** / **Impor JSON** untuk berbagi suite. **Ekspor Excel** / **Ekspor PDF** untuk laporan SIT.

## Persyaratan

- Windows 10/11
- Python 3.11+ (untuk mode pengembangan)
- Google Chrome atau Microsoft Edge (disarankan). Jika tidak ada, JAQA akan mengunduh Chromium sekali.

## Menjalankan dari source

```bat
run.bat
```

atau:

```bat
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
python main.py
```

## Build exe (PyInstaller)

```bat
build.bat
```

Hasil: `dist\JAQA.exe` (satu file, tanpa konsol).

## Format JSON

```json
{
  "app": "JAQA",
  "version": "1.0",
  "name": "JAQA Suite",
  "test_cases": [
    {
      "no_tc": "TC-001",
      "deskripsi": "Login berhasil",
      "aplikasi": "Portal",
      "url": "https://contoh.jalin/",
      "username": "sit.user",
      "password": "secret",
      "expected_result": "Dashboard tampil",
      "steps": [],
      "expectations": []
    }
  ]
}
```

Session terakhir tersimpan di `%APPDATA%\JAQA\session.json`. Screenshot NOK di `%APPDATA%\JAQA\screenshots`.
