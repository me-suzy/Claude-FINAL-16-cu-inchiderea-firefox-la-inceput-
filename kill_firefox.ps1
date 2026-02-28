# kill_firefox.ps1 - Inchide Firefox si geckodriver inainte de rularea scriptului Python
# Foloseste exclusiv PowerShell (tasklist si taskkill se blocheaza pe acest PC)

# --- Firefox ---
$fox = Get-Process -Name firefox -ErrorAction SilentlyContinue
if ($fox) {
    Write-Host ("INAINTE: " + $fox.Count + " procese firefox detectate (PID: " + ($fox.Id -join ', ') + ")")
    $fox | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3

    $fox2 = Get-Process -Name firefox -ErrorAction SilentlyContinue
    if ($fox2) {
        Write-Host ("ATENTIE: Mai sunt " + $fox2.Count + " procese firefox - incerc din nou...")
        $fox2 | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2

        $fox3 = Get-Process -Name firefox -ErrorAction SilentlyContinue
        if ($fox3) {
            Write-Host ("EROARE: " + $fox3.Count + " procese firefox NU s-au inchis!")
        } else {
            Write-Host "OK: Firefox inchis la a doua incercare."
        }
    } else {
        Write-Host "OK: Toate procesele firefox inchise."
    }
} else {
    Write-Host "Firefox nu ruleaza - profilul este liber."
}

# --- Geckodriver ---
$gecko = Get-Process -Name geckodriver -ErrorAction SilentlyContinue
if ($gecko) {
    Write-Host ("Geckodriver: " + $gecko.Count + " procese - inchid...")
    $gecko | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Write-Host "Geckodriver inchis."
} else {
    Write-Host "Geckodriver nu ruleaza."
}

# --- Curata lock-uri profil Firefox ---
$profileBase = Join-Path $env:APPDATA "Mozilla\Firefox\Profiles"
if (Test-Path $profileBase) {
    Get-ChildItem $profileBase -Directory | ForEach-Object {
        foreach ($lockName in 'parent.lock', '.parentlock', 'lock') {
            $lp = Join-Path $_.FullName $lockName
            if (Test-Path $lp) {
                try {
                    Remove-Item $lp -Force
                    Write-Host ("Lock sters: " + $lp)
                } catch {
                    Write-Host ("Nu am putut sterge: " + $lp)
                }
            }
        }
    }
}

Write-Host "Pregatire terminata, pornesc scriptul Python."
