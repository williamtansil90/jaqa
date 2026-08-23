@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Membuat virtual environment...
  py -3 -m venv .venv
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
python -m playwright install chromium

echo.
echo Membangun JAQA.exe ...
pyinstaller --noconfirm --clean jaqa.spec

echo.
echo Selesai. File exe: dist\JAQA.exe
echo Pastikan Google Chrome atau Microsoft Edge terpasang di komputer pengguna.
pause
