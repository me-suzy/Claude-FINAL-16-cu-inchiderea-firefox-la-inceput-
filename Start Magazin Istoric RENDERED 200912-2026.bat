@echo off
chcp 65001 >nul
title Magazin Istoric - recaptura rendered 200912-ultimul

cd /d "%~dp0"

set "MAGAZIN_ISTORIC_USERNAME=YOUR-USER"
set "MAGAZIN_ISTORIC_PASSWORD=YOUR-PASS"

echo.
echo Pornesc recaptura RENDERED pentru Magazin Istoric...
echo Interval: 200912 - ultimul numar gasit in arhiva
echo Script: "%~dp0magazin-ist-rendered.py"
echo PDF-uri finale suprascrise dupa PDF complet: G:\Magazin Istoric
echo Temporare rendered: G:\Magazin Istoric\Temporare_Rendered
echo State separat: "%~dp0state-rendered.json"
echo Timpi: 5 secunde la deschiderea numarului, 3 secunde intre pagini
echo.

where python >nul 2>nul
if %errorlevel%==0 (
    python "%~dp0magazin-ist-rendered.py" --start-code 200912 --first-wait 5 --page-wait 3
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        py -3 "%~dp0magazin-ist-rendered.py" --start-code 200912 --first-wait 5 --page-wait 3
    ) else (
        echo.
        echo Nu gasesc Python in PATH. Instaleaza Python sau adauga-l in PATH.
    )
)

echo.
echo Rulare rendered incheiata.
pause
