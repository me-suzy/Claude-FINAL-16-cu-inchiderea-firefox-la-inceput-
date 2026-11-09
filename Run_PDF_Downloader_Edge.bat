@echo off
REM ===========================================================================
REM   BATCH SCRIPT pentru rularea automata a PDF Downloader - versiunea EDGE
REM   Ruleaza scriptul Python pe Microsoft Edge si logheaza output-ul.
REM   Perechea lui Run_PDF_Downloader.bat (care ruleaza versiunea Firefox).
REM ===========================================================================

REM Seteaza directorul de lucru
cd /d "D:\TEST"

REM Creeaza director pentru log-uri daca nu exista
if not exist "D:\TEST\Logs" mkdir "D:\TEST\Logs"

REM Numele task-ului din Task Scheduler (daca il programezi vreodata)
set "TASK_NAME=PDF Downloader Edge Daily"

REM Genereaza numele fisierului de log cu data curenta
set "LOGFILE=D:\TEST\Logs\PDF_Downloader_Edge_%date:~-4%%date:~3,2%%date:~0,2%_%time:~0,2%%time:~3,2%%time:~6,2%.log"
set "LOGFILE=%LOGFILE: =0%"

REM Fisiere temporare UNICE pe instanta, ca doua rulari sa nu se calce pe ele
set "TMPSTATUS=%TEMP%\task_status_edge_%RANDOM%%RANDOM%.txt"
set "TMPLINE=%TEMP%\task_status_line_edge_%RANDOM%%RANDOM%.txt"
set "TMPGUARD=%TEMP%\guard_edge_%RANDOM%%RANDOM%.txt"

echo =========================================================================== > "%LOGFILE%"
echo   PDF DOWNLOADER - EDGE - START RULARE >> "%LOGFILE%"
echo   Data: %date% %time% >> "%LOGFILE%"
echo =========================================================================== >> "%LOGFILE%"
echo. >> "%LOGFILE%"

REM ===========================================================================
REM   GUARD: nu porni daca ruleaza deja o instanta (Edge SAU Firefox)
REM   Cele doua versiuni impart state.json si skip_urls.json de pe G:.
REM ===========================================================================
echo [GUARD] Verific daca ruleaza deja o instanta a scriptului... >> "%LOGFILE%"
REM Inauntru folosim DOAR ghilimele simple, ca sa nu fie nimic de escapat pentru cmd.
REM "|" este in interiorul argumentului din ghilimele duble, deci cmd nu-l vede ca pipe.
REM Rezultatul trece printr-un fisier temporar ("set /p"), nu prin "for /f".
powershell -NoProfile -NonInteractive -Command "(Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -like '*Sterge pdf pe G *.py*' } | Measure-Object).Count" > "%TMPGUARD%" 2>nul
set "ALREADY="
set /p ALREADY=<"%TMPGUARD%"
del "%TMPGUARD%" >nul 2>&1
if not "%ALREADY%"=="0" if not "%ALREADY%"=="" (
    echo [STOP] Ruleaza deja o instanta a scriptului ^(%ALREADY% proces^). NU pornesc a doua. >> "%LOGFILE%"
    echo [STOP] Cele doua versiuni impart G:\state.json - pornirea a fost anulata. >> "%LOGFILE%"
    echo [STOP] Ruleaza deja o instanta a scriptului. NU pornesc a doua.
    exit /b 2
)
echo [OK] Nicio alta instanta activa. >> "%LOGFILE%"
echo. >> "%LOGFILE%"

REM ===========================================================================
REM   AUTO-VERIFICARE SI REACTIVARE TASK SCHEDULER (daca task-ul exista)
REM ===========================================================================
echo [VERIFICARE] Verific statusul task-ului "%TASK_NAME%"... >> "%LOGFILE%"

schtasks /Query /TN "%TASK_NAME%" /FO LIST > "%TMPSTATUS%" 2>&1
findstr /C:"Status:" "%TMPSTATUS%" > "%TMPLINE%" 2>&1

findstr /C:"Disabled" "%TMPLINE%" >nul 2>&1
if %errorlevel% equ 0 (
    echo [ALERTA] Task-ul este DISABLED! Incerc sa il reactivez... >> "%LOGFILE%"
    schtasks /Change /TN "%TASK_NAME%" /ENABLE >nul 2>&1
    if %errorlevel% equ 0 (
        echo [SUCCES] Task-ul a fost REACTIVAT automat! >> "%LOGFILE%"
    ) else (
        echo [AVERTISMENT] Nu am putut reactiva task-ul ^(lipsa permisiuni admin?^) >> "%LOGFILE%"
    )
) else (
    findstr /C:"Ready" "%TMPLINE%" >nul 2>&1
    if %errorlevel% equ 0 (
        echo [OK] Task-ul este activ si functional ^(Status: Ready^) >> "%LOGFILE%"
    ) else (
        findstr /C:"Running" "%TMPLINE%" >nul 2>&1
        if %errorlevel% equ 0 (
            echo [OK] Task-ul este activ ^(Status: Running^) >> "%LOGFILE%"
        ) else (
            echo [INFO] Task-ul nu exista sau are status necunoscut, continui rularea... >> "%LOGFILE%"
        )
    )
)

del "%TMPSTATUS%" >nul 2>&1
del "%TMPLINE%" >nul 2>&1
echo. >> "%LOGFILE%"

REM ===========================================================================
REM   CURATARE msedgedriver ORFAN
REM   Edge-ul tau normal NU este atins: automatizarea are profil dedicat
REM   (D:\TEST\EdgeProfileArcanum).
REM ===========================================================================
echo [EDGE] Inchid doar msedgedriver orfan ^(Edge-ul tau ramane deschis^)... >> "%LOGFILE%"
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$d = Get-CimInstance Win32_Process -Filter \"Name='msedgedriver.exe'\" -ErrorAction SilentlyContinue; $orf = @($d | Where-Object { -not (Get-Process -Id $_.ParentProcessId -ErrorAction SilentlyContinue) }); if ($orf.Count -gt 0) { $orf | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; Write-Host ('msedgedriver orfan inchis: ' + $orf.Count) } else { Write-Host 'Nu exista msedgedriver orfan de inchis.' }" >> "%LOGFILE%" 2>&1
echo. >> "%LOGFILE%"

REM ===========================================================================
REM   GASIRE PYTHON
REM ===========================================================================
set "PYTHON_EXE="

where python >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_EXE=python"
    goto :found_python
)

if exist "C:\Python311\python.exe" (
    set "PYTHON_EXE=C:\Python311\python.exe"
    goto :found_python
)

if exist "C:\Python310\python.exe" (
    set "PYTHON_EXE=C:\Python310\python.exe"
    goto :found_python
)

if exist "C:\Python39\python.exe" (
    set "PYTHON_EXE=C:\Python39\python.exe"
    goto :found_python
)

if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    goto :found_python
)

if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    goto :found_python
)

if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
    set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    goto :found_python
)

echo EROARE: Python nu a fost gasit! >> "%LOGFILE%"
echo Verifica ca Python este instalat si adauga-l in PATH. >> "%LOGFILE%"
exit /b 1

:found_python
echo Python gasit: %PYTHON_EXE% >> "%LOGFILE%"
echo. >> "%LOGFILE%"

REM Encoding UTF-8 pentru Python (diacritice in loguri)
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1

echo Incepe rularea scriptului ^(EDGE^)... >> "%LOGFILE%"
echo. >> "%LOGFILE%"

"%PYTHON_EXE%" -u "D:\TEST\Claude-FINAL 15 - BUN Sterge pdf pe G Edge.py" >> "%LOGFILE%" 2>&1

REM Capteaza codul de iesire IMEDIAT (altfel se pierde in blocul if)
set "RC=%errorlevel%"

if "%RC%"=="0" (
    echo. >> "%LOGFILE%"
    echo =========================================================================== >> "%LOGFILE%"
    echo   SCRIPTUL S-A TERMINAT CU SUCCES >> "%LOGFILE%"
    echo   Data: %date% %time% >> "%LOGFILE%"
    echo =========================================================================== >> "%LOGFILE%"
) else (
    echo. >> "%LOGFILE%"
    echo =========================================================================== >> "%LOGFILE%"
    echo   SCRIPTUL S-A TERMINAT CU EROARE ^(cod: %RC%^) >> "%LOGFILE%"
    echo   Data: %date% %time% >> "%LOGFILE%"
    echo =========================================================================== >> "%LOGFILE%"
)

exit /b %RC%
