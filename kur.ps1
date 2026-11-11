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
# Bekçi: görev bir sebeple kapanırsa (çökme, elle sonlandırma) 5 dakika içinde yeniden kalkar.
# Önceden yalnız oturum açılışında başlıyordu; düşerse sabaha kadar geçiş olmazdı.
# Çalışırken gelen tetik yok sayılır (IgnoreNew), betik de mutex'le tek kopya kalır.
$bekci    = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
# Süre sınırı sıfır: varsayılan 3 günde görevi durdururdu. Tek kopya çalışır.
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Stop-ScheduledTask -TaskName 'cswap-auto' -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName 'cswap-auto' -Description 'claude-swap: esikte Claude hesabini degistirir' -Action $action -Trigger @($trigger, $bekci) -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName 'cswap-auto'

# Hızlı tetik (~/.claude/kota/ayar.json, varsa) esikte-gec.py'yi tam yolla çağırıyor. Klasör
# taşınınca eski yol "No such file" verip hızlı geçiş sessizce duruyordu (07.11.2026: hesap
# eşikte geçmeyip %100'e dayandı). Yol burada bu klasöre çevrilir.
$kotaAyar = Join-Path $env:USERPROFILE '.claude\kota\ayar.json'
if (Test-Path $kotaAyar) {
    $python = Join-Path (Split-Path $pythonw) 'python.exe'
    # Kodda çift tırnak ve ters bölü yok: PowerShell 5.1 yerel komuta geçirirken bozardı.
    $duzelt = @'
import json, sys
yol, yeni = sys.argv[1], sys.argv[2].replace(chr(92), '/')
with open(yol, encoding='utf-8') as f:
    ayar = json.load(f)
komut = ayar.get('komut') or []
if any(str(k).endswith('esikte-gec.py') for k in komut) and yeni not in komut:
    ayar['komut'] = [yeni if str(k).endswith('esikte-gec.py') else k for k in komut]
    with open(yol, 'w', encoding='utf-8') as f:
        json.dump(ayar, f, ensure_ascii=False, indent=2)
    print('hızlı tetik yolu: ' + yeni)
'@
    & $python -c $duzelt $kotaAyar (Join-Path $PSScriptRoot 'esikte-gec.py')
}

# 5 saatlik pencere başlatma saatleri kaydedildiyse görevi bu klasörün yoluyla yeniden kur:
# klasör taşınınca eski yoldaki betik bulunamaz, görev sessizce boşa tetiklenirdi.
if (Test-Path (Join-Path $env:LOCALAPPDATA 'claude-account-switcher\pencere-baslat.json')) {
    & (Join-Path (Split-Path $pythonw) 'python.exe') (Join-Path $PSScriptRoot 'pencere-baslat.pyw') --kur
}

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
