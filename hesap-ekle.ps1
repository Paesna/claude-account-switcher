# claude-swap'e hesap ekler. Her e-posta için Claude Code girişini açar
# (tarayıcıda onaylanır), giriş beklenen hesapla bittiyse "cswap add" ile
# kaydeder. Yanlış hesapla biten girişi kaydetmez, aynı hesabı yeniden ister.
# Kayıtlı bir hesabı yeniden vermek girişini tazeler ("re-login needed").
#
#   .\hesap-ekle.ps1 ornek@sirket.com
#   .\hesap-ekle.ps1 bir@sirket.com iki@sirket.com uc@sirket.com
# -File ile verilen her e-posta ayrı argüman gelir; yalnız ilki parametreye bağlanırdı.
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Hesaplar)

$env:PYTHONUTF8 = '1'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$cswap = Join-Path $env:USERPROFILE '.local\bin\cswap.exe'
# Claude Code npm ile kurulduysa gerçek exe node_modules altında; yerel kurucu ~/.local/bin'e
# koyuyor. .cmd/.ps1 sarmalayıcısı ProcessStartInfo ile başlatılamadığı için exe aranır.
$claude = @(
    (Join-Path $env:APPDATA 'npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe'),
    (Join-Path $env:USERPROFILE '.local\bin\claude.exe'),
    (Get-Command claude.exe -ErrorAction SilentlyContinue).Source
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $claude) { Write-Host "claude.exe bulunamadı: Claude Code kurulu mu?"; exit 2 }
if (-not $Hesaplar) { Write-Host "Kullanım: .\hesap-ekle.ps1 ornek@sirket.com [baska@sirket.com ...]"; exit 2 }
$girisSiniri = 240   # saniye
Add-Type -AssemblyName System.Windows.Forms

function Giris([string]$eposta) {
    # "claude auth login" tarayıcıda yetki verilmezse sonsuza kadar bekliyordu (28.10:
    # 08:54'te başlayan giriş 5 saat açık kaldı, pencere bütün eklemeleri reddetti).
    # Pencere açmadan başlatılır, süre dolunca alt süreçleriyle birlikte kapatılır.
    $bilgi = New-Object System.Diagnostics.ProcessStartInfo $claude, "auth login --email $eposta"
    $bilgi.UseShellExecute = $false
    $bilgi.CreateNoWindow = $true
    $bilgi.RedirectStandardInput = $true
    $p = [System.Diagnostics.Process]::Start($bilgi)
    if (-not $p.WaitForExit($girisSiniri * 1000)) {
        & taskkill /T /F /PID $p.Id 2>&1 | Out-Null
        Write-Host "Giriş $girisSiniri saniyede tamamlanmadı: tarayıcıda yetki verilmedi."
        return $false
    }
    return $true
}

$eksik = @()
foreach ($eposta in $Hesaplar) {
    $tamam = $false
    for ($deneme = 1; $deneme -le 3 -and -not $tamam; $deneme++) {
        # Tarayıcı claude.ai'da açık hesapla soru sormadan yetki veriyor;
        # kişi doğru hesapla girmeden yetki istenirse giriş önceki hesapla biter.
        Start-Process 'https://claude.ai/logout'
        $cevap = [System.Windows.Forms.MessageBox]::Show(
            "Tarayıcıda claude.ai'a şu hesapla gir:`n`n    $eposta`n`nGirince Tamam'a bas. (İptal: bu hesabı atla)",
            "Hesap ekle: $eposta", 'OKCancel', 'Information', 'Button1',
            [System.Windows.Forms.MessageBoxOptions]::ServiceNotification)
        if ($cevap -ne 'OK') { Write-Host "$eposta atlandı."; break }
        Write-Host ""
        Write-Host ">>> $eposta : tarayıcıda bu hesapla girişi tamamlayın ($deneme. deneme)"
        if (-not (Giris $eposta)) { continue }
        $durum = & $claude auth status | ConvertFrom-Json
        if ($durum.email -eq $eposta) {
            & $cswap add
            $tamam = ($LASTEXITCODE -eq 0)
        } else {
            Write-Host "Giriş $($durum.email) hesabıyla bitti, $eposta bekleniyordu."
            Write-Host "Tarayıcıda claude.ai'dan çıkış yapıp doğru hesabı seçin."
        }
    }
    if (-not $tamam) { $eksik += $eposta }
}

Write-Host ""
& $cswap list
if ($eksik) { Write-Host ""; Write-Host "EKLENEMEYENLER: $($eksik -join ', ')"; exit 1 }
