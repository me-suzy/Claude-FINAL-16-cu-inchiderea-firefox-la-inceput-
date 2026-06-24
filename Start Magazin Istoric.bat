@echo off
chcp 65001 >nul
title Magazin Istoric - download complet

cd /d "%~dp0"

echo.
echo Pornesc downloaderul Magazin Istoric...
echo Script: "%~dp0magazin-ist.py"
echo PDF-uri finale: G:\Magazin Istoric
echo Temporare: G:\Magazin Istoric\Temporare
echo.
set "MAGAZIN_ISTORIC_USERNAME=YOUR-USER"
set "MAGAZIN_ISTORIC_PASSWORD=YOUR-PASS
echo Login automat activ. Sesiunea se pastreaza in cookies.json dupa autentificare.
echo.

where python >nul 2>nul
if %errorlevel%==0 (
    python "%~dp0magazin-ist.py"
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        py -3 "%~dp0magazin-ist.py"
    ) else (
        echo.
        echo Nu gasesc Python in PATH. Instaleaza Python sau adauga-l in PATH.
    )
)

echo.
echo Rulare incheiata.
pause
