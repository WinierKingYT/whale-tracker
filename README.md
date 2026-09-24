# whale-tracker

AI destekli piyasa okuma ve balina takip sistemi. Kripto piyasasını 7/24 izleyen,
büyük oyuncuların (balinaların) hareketlerini, haberleri ve piyasa yapısını
birlikte okuyan, bunlardan anlamlı sinyaller çıkaran ve disiplinli risk
kurallarıyla pozisyon alan bir sistem.

**Felsefe:** Piyasayı tahmin etmeye çalışma; piyasada büyük paranın ne
yaptığını gör, bağlamını anla, riski kontrol ederek arkasından git.

Tam kapsam ve gerekçe: [docs/PROJECT-PLAN.md](docs/PROJECT-PLAN.md).

## Kurulum ve çalıştırma

```powershell
uv sync --dev
uv run pytest tests/ -v
uv run python -m whale_tracker.observe
```

Anahtar/hesap gerekmiyor — Binance public futures API, Alternative.me
Fear&Greed Index, ve ücretsiz bir public Ethereum RPC (publicnode.com)
kullanıyor. Bilinen borsa cüzdanları `data/known-exchange-wallets.json`'da
(kaynak ve doğrulama notları dahil).

### Durum özeti

Kaç aday üretildi, kaçı Kademe 2/3'e ulaştı, açık pozisyon var mı, AI
çağrıları (Hermes/Sonnet/Opus) ne kadar kotanı kullanıyor — tek komut,
gerçek veya simülasyon DB'sine karşı (`--db`):

```powershell
uv run python -m whale_tracker.status
```

### Simülasyon (test aracı)

Gerçek veride Kademe 3'ün "strong" eşiği nadir tetiklendiği için
`paper_trading.py`/`evaluation.py`'yi gerçek veriyle hacimli test etmek
haftalar sürer. `simulate.py`, gerçekçi ama sahte bir borsa akışı
(fiyat/funding/OI random walk, sentetik zincir-üstü transferler, haberler)
üretip **gerçek pipeline'ı** (signal.py, Kademe 1-3, paper trading,
evaluation — hiçbiri değişmemiş) bu veriye karşı hızla, kendi ayrı
`data/simulation.db`'sine yazarak çalıştırır:

```powershell
uv run python -m whale_tracker.simulate --cycles 500 --seed 7
```

AI (Kademe 1/2/3) varsayılan olarak **kapalı** (`--with-ai` ile açılır,
gerçek Hermes/Sonnet/Opus kotanı kullanır) — kapalıyken sentetik ama
açıkça etiketli metin üretilir, ama stop-loss/pozisyon büyüklüğü gibi
deterministik risk matematiği hep gerçek koddan gelir, hiç sahte değildir.

Kurulurken iki gerçek zamanlama hatası (simülatörün wall-clock kullanması,
`signal.py`'nin 24s pencerenin hiç kaymaması) ve bir haber-oranı
kalibrasyonu bulunup düzeltildi — bkz. `simulate.py`/`signal.py`'nin kendi
docstring'leri ve git geçmişi.

**Risk kalibrasyonu ölçülüyor, kör tahminle değil.** `calibrate.py`, aynı
pipeline'ı N bağımsız fiyat yolunda çalıştırıp Aşama 4 skor kartlarını
toplar (`python -m whale_tracker.calibrate --runs 10 --cycles 800`).
10 seed'lik bir çalıştırma mevcut tasarımın (dar hedef/geniş stop, ama
yüksek isabet oranı) net pozitif olduğunu doğruladı; standart "2:1
ödül/risk" düzeltmesi denendi, aynı seed'lerle ölçüldü ve **daha kötü**
çıktığı için geri alındı (isabet oranı %93.8→%12.6, getiri +%0.95→-%1.61)
— bulgu `paper_trading.py`'nin docstring'inde kayıtlı, körü körüne tekrar
denenmesin diye.

## Durum

**Aşama: Gözlemci tamamlandı (1/6), Sinyal üretici tüm sinyalleriyle
çalışıyor (2/6), Kademe 2 devrede.** Beş kaynak uçtan uca test edildi ve
zamanlanmış çalışıyor (Windows Task Scheduler, 15 dakikada bir,
`data/observer.log`): Binance piyasa verisi, Binance günlük mumlar
(teknik/destek-direnç), Fear&Greed, haberler (CoinDesk+Cointelegraph RSS),
zincir üstü büyük USDT/USDC transferleri (bilinen cüzdan/kurum/DEX/
işaretlenmiş adreslerle çapraz kontrollü). Kademe 1 (Hermes ile en büyük
olayların ucuz sınıflandırması) çalışıyor. Sinyal üretici, planın kendi
örneğindeki beş sinyalin hepsini (24s net borsa akışı + funding +
Fear&Greed + haber taraması + teknik/destek-direnç) birbirini doğrulayan
skorlu adaylara dönüştürüyor (`signal.py`) — hiçbir bileşen artık eksik
değil; `sentiment` bileşeni de artık `funding` gibi yön-duyarlı/kontraryan
(gerçek veride bulunan bir açık: Greed her zaman +puan veriyordu, artık
yönle çelişiyorsa 0 veriyor). **Kademe 2** (`sources/analysis.py`), her
sinyal adayı üretildiğinde (nadir, per-cycle değil) Claude Sonnet CLI ile
niteliksel derin analiz üretiyor — bağlam tutarlılığı, en güçlü karşı
senaryo, risk bayrakları; mekanik güven puanını değiştirmiyor, asla al/sat
tavsiyesi üretmiyor. Kullanıcının kendi Claude Pro aboneliğinin paylaşımlı
kotasını kullanıyor (~15K token/çağrı, ölçülmüş), ayrı bir API key
gerekmiyor. **Kademe 3** (`sources/proposal.py`), yalnızca Kademe 2'nin
"strong" dediği adaylarda (en nadir/en pahalı katman) Claude Opus CLI ile
nihai bir KAĞIT ÜZERİNDE işlem önerisi üretiyor — giriş gerekçesi, en kötü
senaryo, karşı argümanlar. Pozisyon büyüklüğü (%1 sermaye tavanı) ve
stop-loss fiyatı AI'ye bırakılmıyor, kod tarafında sabit kurallarla
(section 7, "Değişmez Anayasa") hesaplanıyor. Yön yalnızca `accumulation`
olduğunda öneri üretiliyor (henüz spot-long dışı kapsam yok); teknik
anlık görüntü/destek seviyesi yoksa stop-loss hesaplanamıyor ve öneri hiç
üretilmiyor. **Aşama 3, Paper trading** (`paper_trading.py`) devrede: her
Kademe 3 `long_candidate` önerisi $10.000 sanal sermaye üzerinden kağıt
pozisyona dönüşüyor (büyüklük yine %1 kuralıyla, ~$100/pozisyon). Stop-loss
zaten Kademe 3'ten geliyor; hedef (take-profit) direnç seviyesinden kod
tarafında türetiliyor. Her turda açık pozisyonlar gerçek piyasa fiyatına
karşı kontrol ediliyor — stop, hedef veya 7 gün (swing tarzı üst sınır)
dolunca otomatik kapanıp P&L kaydediliyor. Hâlâ hiçbir aşamada gerçek emir
yok, gerçek para yok — bu tamamen kod içi defter tutma.

**Risk Guard eklendi** (`paper_trading.risk_guard_blocks_new_position`).
Section 7'nin "Değişmez Anayasa"sındaki iki kural artık kod tarafında
uygulanıyor (önceden paper trading'de bile yoktu): aynı anda en fazla 3
açık pozisyon, günlük kayıp sanal sermayenin %3'ünü aşarsa o gün yeni
pozisyon açılmaz. Planın kendi tablosundaki "Risk Guard (kod) — her
işlemde, son söz" rolü budur; Aşama 5'te gerçek para devreye girdiğinde
aynı guard zaten kanıtlanmış olacak.

**Aşama 4, Değerlendirme** (`evaluation.py`) ölçüm altyapısı da hazır —
henüz kapanmış pozisyon yoksa dahi çalışır, ilk pozisyonlar kapandığı an
doğrudan kullanılabilir: isabet oranı, ortalama kazanç/kayıp oranı,
maksimum düşüş (drawdown, tepe-dip takibiyle), ve aynı dönemde BTC-hold
karşılaştırması (`python -m whale_tracker.evaluation`). 10 kapanmış
pozisyonun altında sonuçlar yine gösteriliyor ama "düşük güvenilirlik"
uyarısıyla. `PROJECT-PLAN.md`'nin kendi kriteri işletiliyor: BTC-hold
strateji getirisini geçiyorsa "EVET/HAYIR" doğrudan raporda (karşılaştırma
her zaman BTCUSDT piyasa geçmişine bakıyor, hangi sembollerde işlem
açıldığından bağımsız — plan metninin kendi kriteri budur).

**ETH desteği eklendi.** Section 6 "Başlangıçta BTC ve ETH" diyordu ama
sistem başta yalnızca BTCUSDT izliyordu — artık piyasa/teknik veri, sinyal
üretimi, Kademe 1-3, kağıt pozisyon ve değerlendirme hepsi BTCUSDT +
ETHUSDT için ayrı ayrı çalışıyor (zincir üstü tarama ve haberler paylaşımlı
kalıyor, asset-özel değiller — bilinçli bir basitleştirme). Gerçek canlı
veriyle uçtan uca doğrulandı, mevcut veritabanı sorunsuz göç etti (yeni
`symbol` sütunu, eski kayıtlar BTCUSDT'ye varsayılan).

**Simülasyon ve kalibrasyon eklendi** (`simulate.py`, `calibrate.py`,
`simulation/`) — yukarıdaki bölümlere bak. Gerçek veri yerine geçmiyor,
sadece gerçek pipeline'ı hızlı/hacimli test etmek için; kendi ayrı
`data/simulation.db` dosyasına yazıyor.

**Kota takibi eklendi.** `status.py`'nin "AI çağrıları" bölümü artık
Kademe 1/2/3'ün gerçek deneme/başarı/süre sayılarını gösteriyor —
`observe.py` her döngüde yazıyor. İlk gerçek ölçüm bir sorunu hemen
ortaya çıkardı: Kademe 1 (Hermes) bu oturumdaki yoğun testler yüzünden
ChatGPT/Codex aboneliğinin kendi kota sınırına takılmış (%0 başarı,
~75s/deneme) — geçici, kendiliğinden düzelmesi bekleniyor, koddan
düzeltilecek bir şey yok (hata zarifçe atlanıyor, gözlemci çökmüyor).

**Pencere sorunu kökten çözüldü** (4 denemeden sonra). Gerçek neden:
`hermes.exe` kendi içinde ayrı bir `conhost.exe` ve kendi Python
yorumlayıcısını başlatıyordu — dıştaki çağrıya uygulanan
`CREATE_NO_WINDOW`/`STARTUPINFO` bunu kapsamıyordu. Çözüm:
`sources/_hidden_subprocess.py`'nin `run_hidden_and_reap()`'i her
çağrıdan sonra **tüm süreç ağacını** (`taskkill /F /T`) zorla temizliyor;
zamanlanmış görev de artık `wscript.exe` üzerinden tamamen gizli
çalışıyor (`scripts/register-task.ps1`).

**Gerçek üretim hatası bulundu ve düzeltildi.** `signal.py`'nin
`_NEGATIVE_NEWS_KEYWORDS` listesindeki tek başına `"hack"` kelimesi,
gerçek bir haberdeki "Hack VC" (bir girişim sermayesi şirketi) ismiyle
yanlışlıkla eşleşip saatlerce `accumulation` sinyallerini bastırmış —
`status.py` ile yapılan eleştirel bir inceleme sırasında bulundu.

**Sıradaki:** İlk gerçek kağıt pozisyonların açılıp kapanmasını bekleme
(Kademe 3 "strong" eşiğine ulaşan aday nadir); Huobi/HTX iki bağımsız
yöntemle denendi, bulunamadı, ertelendi.

| Aşama | Durum |
|---|---|
| 1. Gözlemci | ✅ tamamlandı, zamanlanmış çalışıyor |
| 2. Sinyal üretici | ✅ 5 sinyal + Kademe 2 derin analiz + Kademe 3 kağıt öneri, gerçek veriyle doğrulanmadı henüz |
| 3. Paper trading | ✅ kod tamam, simülasyonla doğrulandı, gerçek pozisyon henüz açılmadı (Kademe 3 eşiği nadir) |
| 4. Değerlendirme | ✅ ölçüm altyapısı hazır, simülasyonla doğrulandı, henüz yeterli gerçek kapanmış pozisyon yok |
| 5. Yarı otomatik (onaylı) | beklemede |
| 6. Otomatik | beklemede |

## Kritik sınır

Bu sistemin hiçbir aşamasında, hiçbir aşamada, Claude gerçek bir finansal
işlem (alım/satım/transfer) yürütmez — bu, onayla bile aşılmayan kategorik
bir sınır. Yarı-otomatik ve otomatik aşamalarda işlemi açan şey kullanıcının
kendi onaylı botu/script'idir, bir AI tool-call'ı değil.

## Risk kuralları (değişmez)

- İşlem başına maksimum risk: sermayenin %1'i
- Her işlemin stop-loss'u var
- Günlük maksimum kayıp %3 → aşılırsa sistem o gün durur
- Aynı anda en fazla 2–3 açık pozisyon
- Kaldıraç yok
- API anahtarında para çekme izni yok
- Aylık AI bütçe tavanı; aşılırsa sistem sadece veri toplama katmanında çalışır

## Başarı kriteri

"Çok para kazandı mı" değil: sinyal isabet oranı, ortalama kazanç/kayıp
oranı, maksimum düşüş (drawdown), ve aynı dönemde sadece BTC tutmaktan daha
iyi mi. "Sadece BTC alıp beklemek" yeniliyorsa gerçek parayı artırmayız.
