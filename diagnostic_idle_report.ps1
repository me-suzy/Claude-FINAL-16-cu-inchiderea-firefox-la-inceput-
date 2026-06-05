# ============================================================
#  Diagnostic pentru eroarea "idle_report.exe - Application Error"
#  Cod 0xe0434352 = exceptie .NET (CLR) netratata (poate fi si OutOfMemory).
#  Tot ce face e READ-ONLY (nu modifica nimic). Ruleaza in PowerShell.
#  Raport salvat in: d:\TEST\arcanum_capture\idle_report_diagnostic.txt
# ============================================================

$ErrorActionPreference = "Continue"
$report = "d:\TEST\arcanum_capture\idle_report_diagnostic.txt"
function Log($t) { $t | Tee-Object -FilePath $report -Append }

"" | Out-File $report -Encoding utf8   # reset fisier raport
Log "===== DIAGNOSTIC idle_report.exe  $(Get-Date) ====="

# --- 1) MEMORIE: cat RAM e folosit / liber (teoria 'Chrome consuma resurse') ---
Log "`n--- 1) MEMORIE ---"
try {
  $os = Get-CimInstance Win32_OperatingSystem
  $totMB = [math]::Round($os.TotalVisibleMemorySize/1KB)
  $freeMB = [math]::Round($os.FreePhysicalMemory/1KB)
  $usedPct = [math]::Round(100*($totMB-$freeMB)/$totMB,1)
  Log ("RAM total: {0} MB | liber: {1} MB | folosit: {2}%" -f $totMB,$freeMB,$usedPct)
  $cs = Get-CimInstance Win32_OperatingSystem
  Log ("Commit (virtual) folosit: {0} MB / limita {1} MB" -f `
      ([math]::Round(($cs.TotalVirtualMemorySize-$cs.FreeVirtualMemory)/1KB)), `
      ([math]::Round($cs.TotalVirtualMemorySize/1KB)))
} catch { Log "  (nu am putut citi memoria: $_)" }

# --- 2) TOP procese dupa memorie (vezi chrome/firefox/python) ---
Log "`n--- 2) TOP 15 procese dupa memorie (WorkingSet) ---"
try {
  Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 15 `
    @{N='Proces';E={$_.ProcessName}}, `
    @{N='MB';E={[math]::Round($_.WorkingSet64/1MB)}}, `
    @{N='Id';E={$_.Id}} | Format-Table -AutoSize | Out-String | Log
} catch { Log "  ($_)" }

Log "`n--- Sumar pe aplicatii ---"
foreach ($n in 'chrome','firefox','python','idle_report','geckodriver') {
  try {
    $p = Get-Process $n -ErrorAction SilentlyContinue
    if ($p) {
      $mb = [math]::Round(($p | Measure-Object WorkingSet64 -Sum).Sum/1MB)
      Log ("  {0,-14} {1,3} procese  {2,6} MB" -f $n,$p.Count,$mb)
    } else { Log ("  {0,-14} (nu ruleaza)" -f $n) }
  } catch { Log ("  ({0}: {1})" -f $n,$_) }
}

# --- 3) Unde e idle_report.exe (proces / cale / cine il porneste) ---
Log "`n--- 3) idle_report.exe: localizare ---"
try {
  $proc = Get-CimInstance Win32_Process -Filter "Name='idle_report.exe'" -ErrorAction SilentlyContinue
  if ($proc) { foreach($p in $proc){ Log ("  RULEAZA acum: PID {0}  ->  {1}" -f $p.ProcessId,$p.ExecutablePath) } }
  else { Log "  Nu ruleaza acum." }
} catch { Log "  ($_)" }

Log "  Caut fisierul pe disc (poate dura)..."
try {
  $found = @()
  foreach ($root in @($env:LOCALAPPDATA,$env:APPDATA,$env:ProgramData,"C:\Program Files","C:\Program Files (x86)")) {
    if ($root -and (Test-Path $root)) {
      $found += Get-ChildItem -Path $root -Filter "idle_report.exe" -Recurse -ErrorAction SilentlyContinue -Force |
                Select-Object -ExpandProperty FullName
    }
  }
  if ($found) { $found | ForEach-Object { Log "  GASIT: $_" } } else { Log "  Nu l-am gasit in locatiile uzuale." }
} catch { Log "  ($_)" }

# --- 4) Task-uri programate care contin idle_report ---
Log "`n--- 4) Scheduled Tasks cu 'idle_report' ---"
try {
  $tasks = Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object {
    ($_.Actions.Execute -join ' ') -match 'idle_report' -or $_.TaskName -match 'idle'
  }
  if ($tasks) { $tasks | ForEach-Object { Log ("  {0}  ->  {1}" -f $_.TaskName, ($_.Actions.Execute -join ';')) } }
  else { Log "  Niciun task evident." }
} catch { Log "  ($_)" }

# --- 5) Chei de pornire automata (Run) ---
Log "`n--- 5) Startup (Run keys) cu 'idle_report' ---"
foreach ($k in 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run','HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run') {
  try {
    $props = Get-ItemProperty $k -ErrorAction SilentlyContinue
    if ($props) {
      $props.PSObject.Properties | Where-Object { $_.Value -match 'idle_report' } |
        ForEach-Object { Log ("  {0} = {1}" -f $_.Name,$_.Value) }
    }
  } catch {}
}

# --- 6) Event Log: ce exceptie .NET a aruncat (aici se vede daca e OutOfMemory) ---
Log "`n--- 6) Event Log: ultimele erori idle_report.exe / .NET Runtime ---"
try {
  Get-WinEvent -FilterHashtable @{ LogName='Application'; Level=2 } -MaxEvents 200 -ErrorAction SilentlyContinue |
    Where-Object { $_.Message -match 'idle_report' -or $_.ProviderName -match '\.NET Runtime' } |
    Select-Object -First 6 TimeCreated, ProviderName, @{N='Msg';E={ ($_.Message -replace '\s+',' ').Substring(0,[math]::Min(400,$_.Message.Length)) }} |
    Format-List | Out-String | Log
} catch { Log "  (nu am putut citi event log: $_)" }

Log "`n===== GATA. Raport salvat in: $report ====="
Write-Host "`nGata. Vezi raportul: $report" -ForegroundColor Green
