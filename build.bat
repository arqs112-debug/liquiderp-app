@echo off
rem Buduje dist\LiquidERP (PyInstaller) i instalator dist\LiquidERP-Setup-<wersja>.exe (Inno Setup 6).
rem Wymaga: .venv z requirements-dev.txt; do instalatora: Inno Setup 6 (iscc.exe).
rem Folder w OneDrive: przy bledzie "Odmowa dostepu" wstrzymaj synchronizacje na czas budowania.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3.10 -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt || goto :error
)
for /f %%v in ('".venv\Scripts\python.exe" tools\version_info.py') do set VERSION=%%v
echo Wersja %VERSION%
".venv\Scripts\python.exe" -m PyInstaller LiquidERP.spec --noconfirm --clean || goto :error

set ISCC=
for %%p in ("%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe" "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe") do (
    if exist %%p set ISCC=%%p
)
if not defined ISCC (
    echo Nie znaleziono Inno Setup 6 - zbudowano tylko folder dist\LiquidERP.
    goto :eof
)
%ISCC% /DAppVersion=%VERSION% installer\LiquidERP.iss || goto :error
echo Gotowe: dist\LiquidERP-Setup-%VERSION%.exe
goto :eof

:error
echo Budowanie nie powiodlo sie.
exit /b 1
