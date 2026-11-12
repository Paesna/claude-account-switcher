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
| **Arka plan görevi** (`cswap-auto.pyw`) | `cswap auto`'yu penceresiz ve tek kopya çalıştırır; durursa ya da 15 dakika tek satır yazmazsa (takılma) yeniden başlatır, hiçbir hatada kendisi kapanmaz. Görev Zamanlayıcı her oturum açılışında ve 5 dakikada bir yoklar: bir sebeple düşerse en geç 5 dakikada yeniden kalkar. Elle `/login` ile listede olmayan bir hesaba girerseniz onu kendiliğinden listeye ekler. |
| **Pencere** (`arayuz.pyw` + `arayuz.html`) | Masaüstündeki **Claude hesapları** kısayolu. Tam genişlikte, **sekmeli**: Hesaplar · Haftalık yenilenme · Sıfırlama hakkı · 5 saatlik pencere · Geçişler · Hesap ekle · Orkestra (ayrıntısı aşağıda). Her hesabın 5 saatlik, haftalık ve **Fable** kullanımı, sıfırlanma saati ve durumu (Aktif / Hazır / Dolu / Durduruldu / Okunamıyor). Satırda **Geç**, **Durdur / Aç**, **Sil**, okunamayanda **Yeniden giriş**. Üstte **5 saatlik ve haftalık eşikler + Kaydet**, **En boş hesaba geç**, **+ Hesap ekle**. Sütun başlığına tıklayınca o sütuna göre sıralar, durum süzgeci vardır. Gece boyu açık kalabilir; kod güncellenince pencere kopmadan yeni koda geçer. |
| **Orkestra** (`orkestra/`) | Birden çok yapay zekâ CLI'ını (Claude Code, Google Antigravity, OpenAI Codex, Meta Muse) tek hedef için çalıştırır: şef hedefi alt görevlere böler, işçilere dağıtır, sonuçları birleştirir. Panelin **Orkestra** sekmesinden yönetilir; ayrıca terminal arayüzü de durur (`py orkestra\app.py`). |
| **5 saatlik pencereyi başlatma** (`pencere-baslat.pyw`) | Pencereden saat seçilir (örn. `08:00, 13:00`); her gün o saatte penceresi sürmeyen her hesaba Haiku ile tek kısa mesaj gider (~900 token), hesapların 5 saatlik penceresi o an başlar ve 5 saat sonra sıfırlanır. **Şimdi başlat** ile elle de çalışır. Mesaj `cswap run` ile hesabın kendi profilinden gider: aktif giriş ve açık oturumlar değişmez. Görev Zamanlayıcı'da `claude-pencere-baslat` görevi olarak durur. |
| **Hesap ekleme** (`hesap-ekle.ps1`) | claude.ai çıkış sekmesini ve bir kutu açar; tarayıcıda o hesapla girip **Tamam** dersiniz, gerisi kendiliğinden. Giriş beklenen hesapla bitmezse kaydetmez, yeniden sorar. |
| **Anlık yüzde ve hızlı tetik** (önerilir, `durum-satiri.py` + `esikte-gec.py`) | Claude Code'un durum satırı her yanıtta güncel yüzdeyi verir. Yüzde değiştikçe claude-swap'ın deposuna yazılır: pencere ve otomatik geçiş dakikalık okumayı beklemez. Aktif hesap eşiğe gelince boş hesaba hemen geçilir. Bir oturum yine de sınıra çarparsa `StopFailure` hook'u hesabı anında değiştirir. |
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
5. Eşikleri pencereden kaydedin (5 saatlik ve haftalık eşikler ayrı tutulabilir; örn. 5 saatlik %80, haftalık %90 veya `cswap config set autoswitch.threshold 80` ve `cswap config set autoswitch.weeklyThreshold 90`).

Klasörü sonradan taşırsanız `kur.ps1`'i yeniden çalıştırın (görevin yolu ve varsa
`~/.claude/kota/ayar.json`'daki hızlı tetik yolu birlikte düzelir).

### Hızlı tetik (isteğe bağlı)

`~/.claude/settings.json` içine durum satırını ekleyin (yolu kendi klasörünüze göre değiştirin):

```json
"statusLine": {
  "type": "command",
  "command": "py -3 \"C:/Users/<siz>/claude account switcher/durum-satiri.py\""
}
```

Kendi durum satırı betiğiniz varsa ona eklemeniz yeter: yüzde değiştikçe (birkaç saniyede bir)
`esikte-gec.py --aktar '<json>'`'u arka planda çalıştırsın; json
`{"five_hour": {"used_percentage", "resets_at"}, "seven_day": {...}, "zaman": <unix>}`.
Okumanın hangi hesaba ait olduğunu (geçişten sonra eski hesabı çizen oturumlar olur) ve aynı
pencerede eski bir okuma olup olmadığını `esikte-gec.py` ayırt eder.

Oturum sınıra çarparsa hesabın hemen değişmesi için aynı dosyaya (sınır hatasında Claude Code
bu hook'u çalıştırır; oturum durur, hesap değişir, "devam" yazınca yeni hesapla sürer):

```json
"hooks": {
  "StopFailure": [{"matcher": "rate_limit", "hooks": [{"type": "command", "command": "py",
    "args": ["-3", "C:/Users/<siz>/claude account switcher/esikte-gec.py", "--limit"], "timeout": 60}]}]
}
```

## Pencere sekmeleri

| Sekme | İçerik |
|---|---|
| **Hesaplar** | Özet kartları (aktif hesap, hazır, dolu, haftalıkta dolu, **Fable kullanımı**, durdurulan), duruma göre süzgeç ve tüm hesapların tablosu: 5 saatlik, haftalık ve Fable çubukları, sıfırlanma saatleri. |
| **Haftalık yenilenme** | Hesaplar yenilenme gününe göre gruplu, en yakın üstte; haftalık ve Fable çubukları. Kırmızı: haftalık eşiğin üstünde, o saate kadar geçişte kullanılmaz. Yenilenme saati bilinmeyen hesaplar listelenmez. |
| **Sıfırlama hakkı** | Yalnız sıfırlamanın işe yaradığı dolu hesaplar (5 saatlikte dolu ya da haftalığı 1 günden uzakta dolu), en geç açılacak olan önce. **Sıfırla ↗** claude.ai Kullanım sayfasını açar; sayfada hakkı olmadığını görürsen **Hakkı yok** ile hesabı listeden kaldırırsın (altta "göster" çipiyle geri alınır). |
| **5 saatlik pencere** | Başlatma saatleri, **Şimdi başlat** ve son başlatmanın hesap hesap sonucu. |
| **Geçişler** | Son 40 geçiş: otomatik (eşikte, doldu), hızlı tetik ve elle. |
| **Hesap ekle** | E-postayı yaz, tarayıcıda giriş yap; süren girişin adımı ve İptal. |
| **Orkestra** | Aşağıda. |

**Fable:** `cswap list`, hesabın modele özel haftalık sınırlarını (Fable) `scoped` altında veriyor; pencere onu
Hesaplar ve Haftalık yenilenme tablolarında, özet kartında ve Orkestra'nın kota panelinde gösterir. Hesap
değiştirme kararını etkilemez (cswap 5 saatlik ve haftalık eşiğe bakar), yalnız bilgidir.

## Orkestra

Panelin **Orkestra** sekmesinde bir hedef yazılır; şef (varsayılan Claude Code) hedefi 1-3 alt göreve böler,
seçilen işçilere (Antigravity, Codex, Muse...) dağıtır ve sonuçları birleştirir. Sekmede şef/işçi seçimi, her
ajan için model ve akıl yürütme seviyesi, çalışma klasörü, plan, ajanlar arası yazışma (mesaja basınca tam
içerik), sonuç ve ajan başına canlı çıktı vardır. Son çalışma pencere kapanınca da durur. **Modelleri tara**
CLI'lardan model listesini yeniden okur. Claude her çağrıda o an **aktif hesabı** kullanır: eşikte hesap
kendiliğinden değişmeye devam eder, kota paneli aktif hesabın 5 saatlik, haftalık ve Fable yüzdesini gösterir.

- `orkestra/runner.py` panelin kullandığı başsız çalıştırıcıdır (stdout'a satır satır JSON olay yazar). Panel onu
  ayrı süreç olarak başlatır; **Durdur** süreç ağacını (CLI'larla birlikte) öldürür. Çalışma sürerken panel
  kendini kapatmaz ve yeni koda devretmez.
- İstem komut satırından geçmez: `claude` ve `codex`'e stdin'den, `muse`'a geçici dosyayla gider (`.cmd` kabuğu
  çok satırlı metni bozar, `"` ve `&` komut enjeksiyonuna açar). `agy` gerçek exe olduğu için argümanla çalışır.
- CLI'ların stderr uyarıları canlı çıktıda görünür ama sonuç metnine karışmaz; süreç hatayla biterse ya da
  stdout boşsa stderr sonuca eklenir. Tek çağrı 30 dakikada bitmezse öldürülür.
- Plan JSON'u çıktının içinden (uyarı ya da kod çiti arasından) ayıklanır; şefin seçilmemiş bir işçiye verdiği
  görev seçili işçilere kaydırılır. İşçi seçilmezse şef işi kendisi yürütür.
- Model listesi `orkestra/.models_cache.json` önbelleğindedir (depoya girmez). Bu makinede önbellekteki bazı
  adlar hesaba açık olmayabilir (Codex'in ChatGPT hesabında desteklenmeyen modeller, Muse `muse-spark`):
  model hatası alırsan listeden başka model seç ya da **Modelleri tara**.
- Testler kota yemez: `py -3 orkestra\test_runner.py`. `runner.py --calistir spec.json --sahte` gerçek CLI
  çağırmadan sahte ajanlarla akışı uçtan uca çalıştırır.

## Bilinmesi gerekenler

- **Tarayıcı, claude.ai'da hangi hesap açıksa yetkiyi ona verir**, soru sormaz. Hesap
  eklerken kutuda Tamam'a basmadan önce tarayıcıda o hesapla girmiş olun. Pencere
  "Giriş X ile bitti, Y bekleniyordu" derse tarayıcıdaki hesap yanlıştır.
- **Hesap değiştirmek için `/logout` yapmayın**: çıktığınız hesabın kayıtlı girişi iptal
  olabilir. Diğer hesapla `/login` yapın (görev onu kendiliğinden listeye alır).
- **Neden dakikada bir?** Anthropic'in kullanım bilgisi ucu hesap başına saatte ~30 isteğe
  izin verir, fazlasında bir saate kadar kilitler. claude-swap bu yüzden normalde 3 dakikada
  bir, eşiğe yaklaşınca dakikada bir sorar. Çok oturum açıkken hesap dakikada 15-35 puan
  eriyebilir: dakikalık okuma hem geç görünür hem eşiği kaçırır. Bunun için durum satırının anlık
  yüzdesi depoya aktarılır. Pencere aynı depodan okur, fazladan istek göndermez.
- **Bütün hesaplar eşiğin üstündeyse** hızlı tetik karışmaz: claude-swap ilk sıfırlanacak hesaba
  gider. Oturum sınıra çarparsa aktiften en az 5 puan boş bir hesaba (örn. %96'daki) geçilir.
- claude-swap'ın geçişten sonraki bekleme süresi 60 sn önerilir (varsayılan 300):
  `cswap config set autoswitch.cooldownSeconds 60`. 300 sn'de, eski verisi yüzünden dolu bir
  hesaba geçildiğinde 5 dakika başka hesaba geçilmiyordu.
- **Durdur** hesabı otomatik geçişin dışına alır, girişini silmez. **Sil** hesabı ve kayıtlı
  girişini claude-swap'tan kaldırır; aktif hesap silinemez.
- Giriş tarayıcıda 4 dakikada tamamlanmazsa kapanır ve yeniden sorulur; süren girişi
  pencereden **İptal** edebilirsiniz.
- Bütün hesaplar eşiğin üstündeyse sistem ilk sıfırlanan hesabı bekler.
- **Hangi Claude'u değiştirir?** Claude Code'un terminali ve VS Code eklentisi (ikisi aynı giriş
  dosyasını okur). Claude masaüstü uygulaması ve claude.ai kendi girişini kullanır, onları değiştirmez.
- **Sıfırlama hakkı:** Anthropic hesaplara ara sıra sınır sıfırlama hakkı verir; claude.ai'de
  Ayarlar → Kullanım → *Limit resets* → **Reset for free** ile kullanılır (Claude Code terminalinde yok).
  Pencerenin **Sıfırlama hakkı** sekmesinde dolu hesapların satırında çıkan
  **Sıfırla ↗** o hesabın Kullanım sayfasını kendi tarayıcı profilinde açar
  (`%LOCALAPPDATA%\claude-account-switcher\tarayici`): her hesapla ilk seferde bir kez girilir, sonra hep
  girili açılır, ana tarayıcıda çıkış-giriş gerekmez. Yalnız 5 saatlikte dolu hesapta 5 saatliği sıfırlayan
  hak, haftalıkta dolu hesapta tam sıfırlama işe yarar; haftalığı 1 gün içinde zaten yenilenecek hesapta
  düğme çıkmaz. **Dolu hesaplarda sırayla aç** bu hesapları en geç açılacaktan başlayarak birer birer
  açar; pencere kapanınca sıradaki açılır. "Reset for free"a basmak her zaman kişinin işi: pencere
  sıfırlamayı kendisi yapmaz.
- **5 saatlik pencereyi başlatma:** Anthropic'in 5 saatlik penceresi hesabın ilk mesajıyla başlar. Seçilen
  saatte penceresi zaten süren hesap yeniden başlatılamaz, atlanır; haftalıkta dolu, durdurulan ve
  okunamayan hesaplar da atlanır. Mesaj boş bir klasörde, kullanıcı ayarları (hook'lar, durum satırı,
  MCP) yüklenmeden gider. Bilgisayar o saatte açık olmalı: uykudan 30 dakikadan geç uyanırsa o seferlik
  çalışmaz (pencereler istenmeyen saate kaymasın). Sonuç `pencere-baslat.log`'da.
- **Gece açık bırakırken** bilgisayar uykuya geçmesin: uykuda Claude Code oturumları da,
  geçiş de durur. Dizüstünde prize takılı bırakın (pilde uyku süresi genelde kısadır).

## Güvenlik

- Hesapların giriş anahtarları claude-swap'ın `%USERPROFILE%\.claude-swap-backup\` klasöründe
  düz dosya olarak durur. Bu klasörü ve `cswap export` çıktılarını **paylaşmayın**.
- Pencere yalnız `127.0.0.1`'de dinleyen bir sunucudan gelir ve her açılışta rastgele bir
  anahtar üretir; anahtarı taşımayan istek reddedilir. Tarayıcıda açık başka bir web sayfası
  yerel sunucuya istek atıp hesabınızı değiştiremez.
- Günlükler (`*.log`) hesap e-postalarını içerir; `.gitignore` onları depo dışında tutar.
- **Orkestra işçileri onay istemeden çalışır** (Codex `--dangerously-bypass-approvals-and-sandbox`, Antigravity
  `--dangerously-skip-permissions`; Muse `--approval-mode never` ile, sandbox açık). Seçtiğin **çalışma
  klasöründe** dosya değiştirebilirler; başlatırken klasör ve ajanlar bir kez daha sorulur. Klasör boş
  bırakılırsa projelerine dokunmayan boş bir klasör (`%LOCALAPPDATA%\claude-account-switcher\orkestra\calisma`)
  kullanılır. Model ve akıl yürütme alanları `.cmd` kabuğundan geçtiği için yalnız `A-Za-z0-9._:/[]-`
  karakterlerini kabul eder.

## Kaldırma

```powershell
Unregister-ScheduledTask -TaskName cswap-auto -Confirm:$false
Unregister-ScheduledTask -TaskName claude-pencere-baslat -Confirm:$false -ErrorAction SilentlyContinue
Remove-Item "$([Environment]::GetFolderPath('Desktop'))\Claude hesapları.lnk"
```

claude-swap'ı da kaldırmak için: `cswap purge` ve `pipx uninstall claude-swap`.

## Teşekkür

Hesap geçişinin kendisini [claude-swap](https://github.com/realiti4/claude-swap) (MIT) yapar;
bu depo onun üzerine Windows görevi, pencere ve hesap ekleme akışı ekler.

## Lisans

[MIT](LICENSE)
