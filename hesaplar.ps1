# Bütün Claude hesaplarının kullanımını, ne zaman sıfırlanacağını ve son geçişleri gösterir.
#   .\hesaplar.ps1          bir kez
#   .\hesaplar.ps1 -Izle    dakikada bir yeniler (masaüstündeki "Claude hesapları" kısayolu)
# Kullanım cswap'in ortak deposundan okunur; cswap auto ile aynı aralıkta yenilendiği için
# açık kalması Anthropic'e fazladan istek göndermez.
param([switch]$Izle)

$env:PYTHONUTF8 = '1'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$cswap = Join-Path $env:USERPROFILE '.local\bin\cswap.exe'
$log = Join-Path $PSScriptRoot 'cswap-auto.log'
$tr = [Globalization.CultureInfo]::GetCultureInfo('tr-TR')

function Kalan([datetime]$zaman, [datetime]$simdi) {
    $k = $zaman - $simdi
    if ($k.TotalMinutes -le 0) { return 'şimdi' }
    '{0} sa {1:00} dk' -f [int][math]::Floor($k.TotalHours), $k.Minutes
}

function Goster {
    $simdi = Get-Date
    $ayarDosyasi = Join-Path $env:USERPROFILE '.claude-swap-backup\settings.json'
    $esik = 90
    $haftalikEsik = $null
    if (Test-Path $ayarDosyasi) {
        try {
            $ayarJson = Get-Content $ayarDosyasi -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($ayarJson.autoswitch.threshold) { $esik = [int]$ayarJson.autoswitch.threshold }
            if ($ayarJson.autoswitch.weeklyThreshold) { $haftalikEsik = [int]$ayarJson.autoswitch.weeklyThreshold }
        } catch {}
    }

    $veri = & $cswap list --json | ConvertFrom-Json
    $satirlar = foreach ($a in $veri.accounts) {
        $b = $a.usage.fiveHour
        $yuzde = if ($b -and $null -ne $b.pct) { [int]$b.pct } else { $null }
        $sif = if ($b -and $b.resetsAt) { ([datetimeoffset]::Parse($b.resetsAt)).LocalDateTime } else { $null }
        $h = $a.usage.sevenDay
        # Haftalık pencere sıfırlandıysa depodaki eski yüzde geçersiz.
        $hYuzde = if ($h -and $null -ne $h.pct) { [int]$h.pct } else { $null }
        # 14:59:59.9 gibi geliyor; 30 sn eklenip dakikaya kesilince 15:00 görünür.
        $hSif = if ($h -and $h.resetsAt) { ([datetimeoffset]::Parse($h.resetsAt)).LocalDateTime.AddSeconds(30) } else { $null }
        if ($hSif -and $hSif -le $simdi) { $hYuzde = 0; $hSif = $null }
        $saatlikDolu = ($null -ne $yuzde -and $yuzde -ge $esik)
        $haftalikDolu = ($null -ne $haftalikEsik -and $null -ne $hYuzde -and $hYuzde -ge $haftalikEsik)
        $durum = if ($a.active) { 'AKTİF' }
                 elseif ($a.usageStatus -ne 'ok') { $a.usageStatus }
                 elseif ($saatlikDolu -or $haftalikDolu) { 'dolu' }
                 else { 'hazır' }
        [pscustomobject]@{
            No         = $a.number
            Hesap      = $a.email -replace '@.*$', ''
            '5 saat'   = if ($null -ne $yuzde) { "%$yuzde" } else { '?' }
            Sifirlanma = if ($sif) { $sif.ToString('HH:mm') } else { '-' }
            Kalan      = if ($sif) { Kalan $sif $simdi } else { 'başlamadı' }
            Haftalik   = if ($null -ne $hYuzde) { "%$hYuzde" } else { '' }
            'Hafta yenilenir' = if ($hSif) { $hSif.ToString('ddd dd.MM HH:mm', $tr) } else { '' }
            Durum      = $durum
            Sira       = if ($sif) { $sif } else { [datetime]::MaxValue }
        }
    }

    $esikBilgisi = "5 saat %$esik"
    if ($haftalikEsik) { $esikBilgisi += " · hafta %$haftalikEsik" }
    "Claude hesapları  ·  $($simdi.ToString('dd.MM HH:mm'))  ·  eşikte ($esikBilgisi) en çok kotası kalana geçer"
    ($satirlar | Sort-Object Sira, No | Format-Table No, Hesap, '5 saat', Sifirlanma, Kalan, Haftalik, 'Hafta yenilenir', Durum -AutoSize | Out-String -Width 200).TrimEnd()
    ''

    $hazir = @($satirlar | Where-Object { $_.Durum -in 'hazır', 'AKTİF' })
    $dolu = @($satirlar | Where-Object { $_.Durum -eq 'dolu' } | Sort-Object Sira)
    $ozet = "Kullanılabilir: $($hazir.Count) hesap  ·  dolu: $($dolu.Count)"
    if ($dolu) { $ozet += "  ·  ilk açılacak: $($dolu[0].Hesap) $($dolu[0].Sifirlanma)'de" }
    $ozet
    ''
    'Son geçişler:'
    Select-String -Path $log -Pattern 'Switched|all accounts exhausted' -Encoding UTF8 |
        Select-Object -Last 8 |
        ForEach-Object {
            # Satır: "<zaman>  <saat>  Switched Account-1 -> Account-6 (eposta) (neden)"
            $s = $_.Line
            $zaman = ([datetime]::Parse($s.Substring(0, 19))).ToString('dd.MM HH:mm')
            $metin = ($s -replace '^\S+\s+\S+\s+', '') -replace '@[^)\s]+', '' `
                -replace 'Switched ', '' -replace '\(proactive\)', '(eşikte)' -replace '\(at-limit\)', '(doldu)' `
                -replace 'all accounts exhausted; earliest reset .*', 'bütün hesaplar dolu, bekleniyor'
            "  $zaman  $metin"
        }
}

if (-not $Izle) { Goster; return }
while ($true) {
    $cikti = Goster | Out-String
    Clear-Host
    $cikti
    'Dakikada bir yenilenir. Kapatmak için pencereyi kapat.'
    Start-Sleep -Seconds 60
}
