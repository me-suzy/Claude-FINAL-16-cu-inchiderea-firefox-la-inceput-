@echo off
REM ═══════════════════════════════════════════════════════════════════════════
REM   BATCH SCRIPT pentru rularea automată a PDF Downloader
REM   Acest script rulează scriptul Python și loghează output-ul
REM ═══════════════════════════════════════════════════════════════════════════

REM Setează directorul de lucru
cd /d "D:\TEST"

REM Creează director pentru log-uri dacă nu există
if not exist "D:\TEST\Logs" mkdir "D:\TEST\Logs"

REM Generează numele fișierului de log cu data curentă
set "LOGFILE=D:\TEST\Logs\PDF_Downloader_%date:~-4%%date:~3,2%%date:~0,2%_%time:~0,2%%time:~3,2%%time:~6,2%.log"
set "LOGFILE=%LOGFILE: =0%"

echo ═══════════════════════════════════════════════════════════════════════════ > "%LOGFILE%"
echo   PDF DOWNLOADER - START RULARE >> "%LOGFILE%"
echo   Data: %date% %time% >> "%LOGFILE%"
echo ═══════════════════════════════════════════════════════════════════════════ >> "%LOGFILE%"
echo. >> "%LOGFILE%"

REM ═══════════════════════════════════════════════════════════════════════════
REM   AUTO-VERIFICARE ȘI REACTIVARE TASK SCHEDULER
REM ═══════════════════════════════════════════════════════════════════════════
echo [VERIFICARE] Verific statusul task-ului "PDF Downloader Daily"... >> "%LOGFILE%"

REM Verifică statusul task-ului
schtasks /Query /TN "PDF Downloader Daily" /FO LIST > "%TEMP%\task_status.txt" 2>&1

REM Caută linia cu Status
findstr /C:"Status:" "%TEMP%\task_status.txt" > "%TEMP%\task_status_line.txt" 2>&1

REM Verifică dacă task-ul este Disabled
findstr /C:"Disabled" "%TEMP%\task_status_line.txt" >nul 2>&1
if %errorlevel% equ 0 (
    echo [ALERTĂ] Task-ul este DISABLED! Încerc să îl reactivez... >> "%LOGFILE%"
    
    REM Încearcă să reactiveze task-ul
    schtasks /Change /TN "PDF Downloader Daily" /ENABLE >nul 2>&1
    
    if %errorlevel% equ 0 (
        echo [SUCCES] Task-ul a fost REACTIVAT automat! >> "%LOGFILE%"
    ) else (
        echo [AVERTISMENT] Nu am putut reactiva task-ul (lipsă permisiuni admin?) >> "%LOGFILE%"
        echo [INFO] Task-ul va continua să ruleze, dar verifică manual statusul! >> "%LOGFILE%"
    )
) else (
    REM Verifică dacă task-ul este Ready sau Running
    findstr /C:"Ready" "%TEMP%\task_status_line.txt" >nul 2>&1
    if %errorlevel% equ 0 (
        echo [OK] Task-ul este activ și funcțional (Status: Ready) >> "%LOGFILE%"
    ) else (
        findstr /C:"Running" "%TEMP%\task_status_line.txt" >nul 2>&1
        if %errorlevel% equ 0 (
            echo [OK] Task-ul este activ (Status: Running) >> "%LOGFILE%"
        ) else (
            echo [INFO] Task-ul are status necunoscut, continui rularea... >> "%LOGFILE%"
        )
    )
)

REM Curăță fișierele temporare
del "%TEMP%\task_status.txt" >nul 2>&1
del "%TEMP%\task_status_line.txt" >nul 2>&1

echo. >> "%LOGFILE%"

echo. >> "%LOGFILE%"

REM ═══════════════════════════════════════════════════════════════════════════
REM   ÎNCHIDERE FIREFOX ȘI GECKODRIVER ÎNAINTE DE PYTHON
REM   IMPORTANT: NU folosim tasklist sau taskkill (ambele se BLOCHEAZĂ pe acest PC).
REM   Folosim EXCLUSIV PowerShell Get-Process / Stop-Process.
REM ═══════════════════════════════════════════════════════════════════════════
echo [FIREFOX] === DEBUG: Context rulare === >> "%LOGFILE%"
echo [FIREFOX] Utilizator: %USERNAME% >> "%LOGFILE%"
echo [FIREFOX] Sesiune: %SESSIONNAME% >> "%LOGFILE%"
echo [FIREFOX] Computername: %COMPUTERNAME% >> "%LOGFILE%"
echo [FIREFOX] Director curent: %CD% >> "%LOGFILE%"

echo [FIREFOX] === Inchid Firefox si geckodriver cu PowerShell === >> "%LOGFILE%"
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "D:\TEST\kill_firefox.ps1" >> "%LOGFILE%" 2>&1
echo. >> "%LOGFILE%"

REM ═══════════════════════════════════════════════════════════════════════════
REM   GĂSIRE PYTHON
REM ═══════════════════════════════════════════════════════════════════════════
REM Găsește Python (verifică mai multe locații posibile)
set "PYTHON_EXE="

REM Verifică Python în PATH
where python >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_EXE=python"
    goto :found_python
)

REM Verifică Python 3.11
if exist "C:\Python311\python.exe" (
    set "PYTHON_EXE=C:\Python311\python.exe"
    goto :found_python
)

REM Verifică Python 3.10
if exist "C:\Python310\python.exe" (
    set "PYTHON_EXE=C:\Python310\python.exe"
    goto :found_python
)

REM Verifică Python 3.9
if exist "C:\Python39\python.exe" (
    set "PYTHON_EXE=C:\Python39\python.exe"
    goto :found_python
)

REM Verifică Python din AppData
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    goto :found_python
)

if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
    set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    goto :found_python
)

REM Python nu a fost găsit
echo EROARE: Python nu a fost găsit! >> "%LOGFILE%"
echo Verifică că Python este instalat și adaugă-l în PATH. >> "%LOGFILE%"
exit /b 1

:found_python
echo Python găsit: %PYTHON_EXE% >> "%LOGFILE%"
echo. >> "%LOGFILE%"

REM Setează encoding UTF-8 pentru Python (rezolvă problema cu emoji-uri)
set PYTHONIOENCODING=utf-8

REM Rulează scriptul Python și capturează output-ul
echo Începe rularea scriptului... >> "%LOGFILE%"
echo. >> "%LOGFILE%"

"%PYTHON_EXE%" "D:\TEST\Claude-FINAL 15 - BUN Sterge pdf pe G Firefox.py" >> "%LOGFILE%" 2>&1

REM Verifică codul de ieșire
if %errorlevel% equ 0 (
    echo. >> "%LOGFILE%"
    echo ═══════════════════════════════════════════════════════════════════════════ >> "%LOGFILE%"
    echo   SCRIPTUL S-A TERMINAT CU SUCCES >> "%LOGFILE%"
    echo   Data: %date% %time% >> "%LOGFILE%"
    echo ═══════════════════════════════════════════════════════════════════════════ >> "%LOGFILE%"
) else (
    echo. >> "%LOGFILE%"
    echo ═══════════════════════════════════════════════════════════════════════════ >> "%LOGFILE%"
    echo   SCRIPTUL S-A TERMINAT CU EROARE ^(cod: %errorlevel%^) >> "%LOGFILE%"
    echo   Data: %date% %time% >> "%LOGFILE%"
    echo ═══════════════════════════════════════════════════════════════════════════ >> "%LOGFILE%"
)

exit /b %errorlevel%

