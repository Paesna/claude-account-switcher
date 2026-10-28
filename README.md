# Claude Account Switcher (Windows)

Birden çok Claude hesabınız varsa Claude Code'u, aktif hesap kotasının eşiğine
(varsayılan **%90**) gelince kendiliğinden **en çok kotası kalan** hesaba geçirir.
Bütün hesapları tıklanabilir bir pencerede gösterir: kullanım, sıfırlanma saati,
son geçişler; tek tıkla geçme, durdurma, silme, yeniden giriş, hesap ekleme.

> **English:** Automatic multi-account switching for Claude Code on Windows, built on
> [claude-swap](https://github.com/realiti4/claude-swap). A hidden background runner
> switches to the account with the most quota left when the active one reaches the
> threshold; a click-to-manage dashboard shows usage and reset times and lets you
> switch / pause / remove / re-login / add accounts and save the threshold.
> UI, scripts and comments are in Turkish.

Geçiş giriş dosyası üzerinden yapılır: tarayıcı açılmaz, fare ve klavye kullanılmaz.
Açık Claude Code oturumları yeniden başlatmadan, bir sonraki mesajda yeni hesapla devam eder.

## Neler var

| Parça | Ne yapar |
|---|---|
| **Arka plan görevi** (`cswap-auto.pyw`) | `cswap auto`'yu penceresiz ve tek kopya çalıştırır, durursa yeniden başlatır. Görev Zamanlayıcı her oturum açılışında başlatır. Elle `/login` ile listede olmayan bir hesaba girerseniz onu kendiliğinden listeye ekler. |
| **Pencere** (`arayuz.pyw` + `arayuz.html`) | Masaüstündeki **Claude hesapları** kısayolu. Her hesabın 5 saatlik kullanımı, sıfırlanma saati ve durumu (Aktif / Hazır / Dolu / Durduruldu / Okunamıyor). Satırda **Geç**, **Durdur / Aç**, **Sil**, okunamayanda **Yeniden giriş**. Üstte **eşik + Kaydet**, **En boş hesaba geç**, **+ Hesap ekle**. Son 15 geçiş. |
| **Hesap ekleme** (`hesap-ekle.ps1`) | claude.ai çıkış sekmesini ve bir kutu açar; tarayıcıda o hesapla girip **Tamam** dersiniz, gerisi kendiliğinden. Giriş beklenen hesapla bitmezse kaydetmez, yeniden sorar. |
| **Hızlı tetik** (isteğe bağlı, `durum-satiri.py` + `esikte-gec.py`) | Claude Code'un durum satırı her yanıtta güncel yüzdeyi verir; eşik görülür görülmez geçer, dakikalık kontrolü beklemez. |
| **Terminal tablosu** (`hesaplar.ps1`) | Pencere yerine komut satırında tek bakış. `-Izle` ile dakikada bir yenilenir. |
| **Kurulum** (`kur.ps1`) | Görevi kurar ve başlatır, masaüstü kısayolunu koyar. |

## Gereksinimler

- Windows 10 / 11
- [Python 3.12+](https://www.python.org/downloads/) (python.org kurucusu; Microsoft Store kısayolu değil)
- [claude-swap](https://github.com/realiti4/claude-swap): `pipx install claude-swap` ya da `uv tool install claude-swap`
- [Claude Code](https://docs.claude.com/en/docs/claude-code) (CLI), en az bir hesapla giriş yapılmış
- Chrome ya da Edge (pencere uygulama modunda açılır; yoksa varsayılan tarayıcı)

## Kurulum

1. claude-swap'ı kurun ve şu anki hesabınızı ekleyin:
   ```powershell
   pipx install claude-swap
   cswap add
   ```
2. Bu depoyu indirin (ya da ZIP olarak) istediğiniz bir klasöre açın.
3. O klasörde PowerShell açıp kurulumu çalıştırın:
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\kur.ps1
   ```
   `görev: Running` ve masaüstünde **Claude hesapları** kısayolu görünmeli.
4. Kısayolu açın, **+ Hesap ekle** ile öteki hesaplarınızı tek tek ekleyin.
5. Eşiği pencereden kaydedin (ya da `cswap config set autoswitch.threshold 90`).

Klasörü sonradan taşırsanız `kur.ps1`'i yeniden çalıştırın.

### Hızlı tetik (isteğe bağlı)

`~/.claude/settings.json` içine durum satırını ekleyin (yolu kendi klasörünüze göre değiştirin):

```json
"statusLine": {
  "type": "command",
  "command": "py -3 \"C:/Users/<siz>/claude account switcher/durum-satiri.py\""
}
```

Kendi durum satırı betiğiniz varsa ona eklemeniz yeter: 5 saatlik yüzde eşiğe gelince
`esikte-gec.py`'yi (pencere başına bir kez) çalıştırsın.

## Bilinmesi gerekenler

- **Tarayıcı, claude.ai'da hangi hesap açıksa yetkiyi ona verir**, soru sormaz. Hesap
  eklerken kutuda Tamam'a basmadan önce tarayıcıda o hesapla girmiş olun. Pencere
  "Giriş X ile bitti, Y bekleniyordu" derse tarayıcıdaki hesap yanlıştır.
- **Hesap değiştirmek için `/logout` yapmayın**: çıktığınız hesabın kayıtlı girişi iptal
  olabilir. Diğer hesapla `/login` yapın (görev onu kendiliğinden listeye alır).
- **Neden dakikada bir?** Anthropic'in kullanım bilgisi ucu hesap başına saatte ~30 isteğe
  izin verir, fazlasında bir saate kadar kilitler. claude-swap bu yüzden normalde 3 dakikada
  bir, eşiğe yaklaşınca dakikada bir sorar. Çok oturum açıkken hesap dakikada birkaç puan
  eriyebilir; bunun için hızlı tetik var. Pencere aynı depodan okur, fazladan istek göndermez.
- **Durdur** hesabı otomatik geçişin dışına alır, girişini silmez. **Sil** hesabı ve kayıtlı
  girişini claude-swap'tan kaldırır; aktif hesap silinemez.
- Giriş tarayıcıda 4 dakikada tamamlanmazsa kapanır ve yeniden sorulur; süren girişi
  pencereden **İptal** edebilirsiniz.
- Bütün hesaplar eşiğin üstündeyse sistem ilk sıfırlanan hesabı bekler.

## Güvenlik

- Hesapların giriş anahtarları claude-swap'ın `%USERPROFILE%\.claude-swap-backup\` klasöründe
  düz dosya olarak durur. Bu klasörü ve `cswap export` çıktılarını **paylaşmayın**.
- Pencere yalnız `127.0.0.1`'de dinleyen bir sunucudan gelir ve her açılışta rastgele bir
  anahtar üretir; anahtarı taşımayan istek reddedilir. Tarayıcıda açık başka bir web sayfası
  yerel sunucuya istek atıp hesabınızı değiştiremez.
- Günlükler (`*.log`) hesap e-postalarını içerir; `.gitignore` onları depo dışında tutar.

## Kaldırma

```powershell
Unregister-ScheduledTask -TaskName cswap-auto -Confirm:$false
Remove-Item "$([Environment]::GetFolderPath('Desktop'))\Claude hesapları.lnk"
```

claude-swap'ı da kaldırmak için: `cswap purge` ve `pipx uninstall claude-swap`.

## Teşekkür

Hesap geçişinin kendisini [claude-swap](https://github.com/realiti4/claude-swap) (MIT) yapar;
bu depo onun üzerine Windows görevi, pencere ve hesap ekleme akışı ekler.

## Lisans

[MIT](LICENSE)
