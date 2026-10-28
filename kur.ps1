# Kurulum: "cswap-auto" görevini kurar (varsa yeniler) ve başlatır, masaüstüne
# "Claude hesapları" kısayolunu koyar. Klasör taşınırsa yeniden çalıştırın.
#
# Görev her oturum açılışında cswap-auto.pyw'yi pythonw ile başlatır: konsolu olmadığı
# için pencere açılmaz (powershell -WindowStyle Hidden, Windows Terminal varsayılan
# konsolken gizlenmiyordu).

$cswap = Join-Path $env:USERPROFILE '.local\bin\cswap.exe'
if (-not (Test-Path $cswap)) {
    Write-Host "cswap bulunamadı ($cswap). Önce: pipx install claude-swap  (ya da: uv tool install claude-swap)"
    exit 2
}

# PATH'teki python/pythonw çoğu makinede Microsoft Store kısayolu: çalışmaz, "Python
# bulunamadı" der. Gerçek yorumlayıcı önce py başlatıcısından sorulur.
$pythonw = $null
try {
    $py = (& py -3 -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1)
    if ($py) { $pythonw = Join-Path (Split-Path $py) 'pythonw.exe' }
} catch {}
if (-not $pythonw -or -not (Test-Path $pythonw)) {
    $pythonw = Get-Command pythonw.exe -All -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notmatch 'WindowsApps' } | Select-Object -First 1 -ExpandProperty Source
}
if (-not $pythonw) { Write-Host "pythonw.exe bulunamadı: python.org'dan Python 3.12+ kurun."; exit 2 }

$script   = Join-Path $PSScriptRoot 'cswap-auto.pyw'
$action   = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$script`"" -WorkingDirectory $PSScriptRoot
$trigger  = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
# Süre sınırı sıfır: varsayılan 3 günde görevi durdururdu. Tek kopya çalışır.
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Stop-ScheduledTask -TaskName 'cswap-auto' -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName 'cswap-auto' -Description 'claude-swap: esikte Claude hesabini degistirir' -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName 'cswap-auto'

$kisayol = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Claude hesapları.lnk'
$k = (New-Object -ComObject WScript.Shell).CreateShortcut($kisayol)
$k.TargetPath = $pythonw
$k.Arguments = '"' + (Join-Path $PSScriptRoot 'arayuz.pyw') + '"'
$k.WorkingDirectory = $PSScriptRoot
$k.Description = 'Claude hesapları: kullanım, sıfırlanma, geçiş, durdurma'
$k.Save()

Start-Sleep -Seconds 3
$g = Get-ScheduledTask -TaskName 'cswap-auto'
"görev: $($g.State), süre sınırı: $($g.Settings.ExecutionTimeLimit)"
"kısayol: $kisayol"
"pythonw: $pythonw"
