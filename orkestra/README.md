> **Claude hesapları paneline bağlı.** Bu klasör panelin (`arayuz.pyw`) **Orkestra** sekmesi olarak çalışır:
> panel görevi `runner.py` ile başlatır, plan, ajanlar arası yazışma ve çıktıyı canlı gösterir.
> `runner.py` panelin kullandığı başsız çalıştırıcıdır (her olayı tek satır JSON olarak yazar);
> klavye odaklı TUI de aşağıdaki gibi `py app.py` ile ayrıca açılır.
> İstemler komut satırına değil stdin'e ya da geçici dosyaya konur (`.cmd` kabuğunda komut enjeksiyonu olmasın).

# ⚡ AI CLI Orchestrator

Tamamen klavye ve görev odaklı, profesyonel bir çoklu yapay zeka ajan yönetim terminali.

Sistemde yüklü olan gerçek CLI araçlarından (**Claude Code**, **Google AGY**, **OpenAI Codex**, **Meta Muse Code**) modelleri ve akıl yürütme seviyelerini (`/model` ve `/effort`) anlık olarak çeker, tek pencerede orkestre eder.

---

## 🎯 Ekran Düzeni ve Kullanım

Ekranda Şef Seçimi, Modeller, Akıl Yürütme ve **Ana Görev (Prompt) Kutusu** yer alır:

```text
┌───────────────────────────────────────────────┬─────────────────────────────────────────────────────────────┐
│ ⚡ AI ORCHESTRATOR    │ ŞEF: Claude Code      │ MODEL: sonnet │ EFFORT: max  │ TOPLAM TOKEN: 0              │
├───────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
│ [1] ORKESTRA ŞEFİ                             │ 🌟 Ana Görev & Plan [F1] │ Claude [F2] │ AGY [F3] │ Codex [F4]│
│  ★ [C] Claude Code                            │                                                             │
│    [G] Google Antigravity (AGY)               │ 🎯 ORKESTRA ŞEFİNE GÖREV VER (ANA PROMPT):                  │
│    [X] OpenAI Codex                           │ ┌─────────────────────────────────────────────┐ ┌─────────┐ │
│    [M] Meta Muse Code                         │ │ Buraya şefe vermek istediğiniz hedefi yazın │ │▶ BAŞLAT │ │
│                                               │ └─────────────────────────────────────────────┘ └─────────┘ │
│ [2] MODELLER (/model)                         │                                                             │
│  ● sonnet (balanced)                          │ 📋 AKTİF GÖREV PLANI (ŞEFİN DAĞITTIĞI İŞLER)                │
│    opus (reasoning)                           │ • Görev 1: Auth analizi │ İşçi: AGY │ Durum: BİTTİ          │
│    haiku (fast)                               │                                                             │
│                                               │ 💬 AJANLAR ARASI CANLI YAZIŞMALAR VE SENTEZ                 │
│ [3] AKIL YÜRÜTME (/effort)                    │ [10:45:10] Şef ➔ AGY: Token doğrulamasını incele            │
│    low                                        │ [10:45:14] AGY ➔ Şef: Eksik kontroller tamamlandı           │
│    medium                                     │                                                             │
│    high                                       │                                                             │
│    xhigh                                      │                                                             │
│  ◆ max                                        │                                                             │
│    ultra                                      │                                                             │
├───────────────────────────────────────────────┴─────────────────────────────────────────────────────────────┤
│ [Hızlı Komut] /model <ad>, /effort <seviye>, /chief <şef>, /refresh, /clear, /quit                          │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 💡 Şefe Nasıl Görev Verilir?

1. **Uygulamayı Açın:** Doğrudan ortadaki **"🎯 ORKESTRA ŞEFİNE GÖREV VER (ANA PROMPT)"** kutusu odaklanmış olarak açılır.
2. **Görevinizi Yazın:** Örn: `Kullanıcı profil servisini JWT ile doğrula ve testlerini yaz`
3. **Başlatın:** `Enter` tuşuna basın veya `[▶ BAŞLAT]` butonuna tıklayın.
4. **Şef İşi Yönetir:**
   - Şef hedefi analiz eder.
   - İşi alt görevlere bölüp plan kutusuna ekler.
   - İşçi yapay zekalara (AGY, Codex, Muse vb.) görevleri dağıtır.
   - Aralarındaki canlı konuşmaları aşağıdaki pencereden izleyebilirsiniz.
   - İşçilerden gelen sonuçları birleştirip nihai çözümü sunar.

---

## ⌨️ Klavye Kısayolları

| Tuş / Kısayol | Fonksiyon |
|---|---|
| **`p`** | Doğrudan Ana Görev (Prompt) kutusuna odaklanır |
| **`Tab` / `Shift+Tab`** | Paneller arasında geçiş yapar (Prompt ➔ Şef ➔ Modeller ➔ Effort ➔ Komut) |
| **`↑` / `↓` veya `j` / `k`** | Listelerdeki seçenekler arasında gezinir |
| **`Enter`** | Vurgulanan seçeneği onaylar veya görevi şefe iletir |
| **`/`** | En alttaki hızlı slash komut satırına odaklanır |
| **`r`** | CLI modellerini yeniden tarar |
| **`F1` - `F5`** | Ham terminal çıktıları ve ana diyalog arasında geçiş yapar |
| **`Ctrl+Q`** | Uygulamadan çıkar |

---

## 🚀 Başlatma

```powershell
# bu klasörde:
py app.py
```
