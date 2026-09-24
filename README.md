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
Standart "2:1 ödül/risk" düzeltmesi denendi, base_seed=200 ile ölçüldü
ve **daha kötü** çıktığı için geri alındı (isabet oranı %93.8→%12.6,
getiri +%0.95→-%1.61) — bulgu `paper_trading.py`'nin docstring'inde
kayıtlı, körü körüne tekrar denenmesin diye.

**2026-09-24 güncellemesi: "net pozitif" bulgusu artık aynı şekilde
doğrulanmıyor, bu satır düzeltildi.** Risk Guard eklendikten ve bu
oturumdaki diğer düzeltmelerden (haber oranı, "hack" kelimesi, saat
hataları) sonra base_seed=0 ile taze bir kalibrasyon çalıştırıldı:
ortalama strateji getirisi **-%0.02**, çalıştırmaların yalnızca **%28.6'sı
net pozitif** — artık net bir "pozitif" iddiası değil, breakeven'a yakın.
Risk Guard'ın kendi katkısını izole etmek için aynı 10 seed'le kontrollü
bir A/B yapıldı (Risk Guard açık/kapalı, başka hiçbir şey değişmeden):

| | Risk Guard AÇIK | Risk Guard KAPALI |
|---|---|---|
| Ort. kapanmış pozisyon/çalıştırma | 8.9 | 69.1 |
| Ort. isabet oranı | %50.9 | %44.4 |
| Ort. strateji getirisi | -%0.02 | -%0.23 |
| Ort. maksimum düşüş | %0.05 | %0.73 |
| Net pozitif çalıştırma oranı | %28.6 | %42.9 |

Sonuç: Risk Guard işini yapıyor — maksimum düşüşü ~14x azaltıyor (aynı
anda en fazla 3 pozisyon + günlük kayıp freni sayesinde), ortalama
getiriyi de hafifçe iyileştiriyor. Ama alttaki yapısal örüntüyü
(ortalama kazanç, ortalama kayıptan tutarlı şekilde küçük) **düzeltmiyor**
— bu onun işi değil, zaten tasarım amacı "son söz" olmak, getiriyi
optimize etmek değil.

**Tampon asimetrisi köküne kadar kazıldı — ve düzeltilmedi, bilinçli
olarak.** Gerçek kapanmış pozisyonlara bakınca mekanik neden net çıktı:
`proposal.py`'nin stop tamponu (%2) ile `paper_trading.py`'nin hedef
tamponu (%0.5) arasında 4 kat fark var — giriş anındaki implied
ödül:risk oranı medyan **0.045** (stop, hedeften ~20 kat uzak). Aynı 10
seed'le iki aday test edildi (tamponlar %1/%1 ve %0.5/%0.5'e
eşitlenerek): mekanizma tahmin ettiği gibi çalıştı, ortalama kayıp
tutarlı şekilde küçüldü (-%2.42 → -%1.58 → -%0.94) — ama **net strateji
getirisi üçünde de aynı yerde kaldı** (-%0.02, -%0.01, -%0.02), ve
%0.5/%0.5 en kötü isabet oranını (%41.7) ve en az net-pozitif
çalıştırmayı (%14.3) verdi (sıkı stop, gürültüden daha sık tetikleniyor).
Kazanç büyüklüğü ile isabet oranı neredeyse tam birbirini götürüyor.
**Canlı sabitler değiştirilmedi.** Gerçek sonuç bir "doğru tampon
sayısı" arayışı değil: sürüklenmesiz bir GBM rastgele yürüyüşünün
yapısı gereği hiçbir mekanik stop/hedef kombinasyonu gerçek bir kenar
(edge) gösteremez — bu stratejinin gerçek bir kenarı olup olmadığı
ancak gerçek fiyat verisiyle (GBM'in taklit edemeyeceği gerçek balina/
duygu/haber sinyal içeriğiyle) cevaplanabilir, tam olarak gerçek kağıt
trading'in var olma sebebi. Bulgu `paper_trading.py`'nin docstring'inde
kayıtlı — `calibrate.py`'nin kendi "tuner değil, diagnostic" uyarısını
doğruluyor, körü körüne yeniden ayar aranmasın diye.

### Backtest (gerçek geçmiş veriyle)

```
set WHALE_TRACKER_ARCHIVE_RPC_URL=https://eth-mainnet.g.alchemy.com/v2/<anahtarın>
uv run python -m whale_tracker.backtest --days 30
```

Son N günün gerçek Binance fiyat/funding, Fear&Greed ve bilinen borsa
cüzdanlarının USDT/USDC akış geçmişini indirip (bir kez, `data/backtest-cache/`
altında önbelleğe) aynı gerçek pipeline'dan (`simulate.run_cycle`, değişmeden)
geçirir; kendi `data/backtest.db` dosyasına yazar. İki şekilde skorlar: planın
Aşama 4 skor kartı ve **rastgele giriş karşılaştırması** — aynı dönemde, aynı
stop/hedef/süre kurallarıyla rastgele anlarda açılan işlemlere karşı; "sinyalin
zamanlaması gerçekten bir şey katıyor mu" sorusunu asıl bu cevaplar.
Geleceğe bakma (lookahead) yok: her an için yalnızca o ana kadar kapanmış veri
görünür (testlerle korunuyor). Zincir üstü geçmiş için **arşiv erişimli bir RPC
gerekli**: üretimin anahtarsız publicnode'u 1-2 günden eski logları vermiyor,
2026-09-24'te denenen diğer anahtarsız RPC'lerin hiçbiri de uygun değildi.
Sınırlamalar (sentetik Kademe 2/3, haber arşivi yok, bugünkü cüzdan listesi)
her çıktının sonunda yazdırılıyor.

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
ChatGPT/Codex aboneliğinin kendi kota sınırına takılmış — geçici bir
blip değil, 8 kesintisiz gerçek döngü boyunca %0 başarı (0/39 çağrı,
~68s/deneme) olarak doğrulandı (`hermes doctor` ile hesabın kendisinin
sağlıklı/giriş yapılmış olduğu, sorunun tamamen kota tarafında olduğu
teyit edildi). Koddan düzeltilebilecek bir hata değil, ama her denemenin
~68s'yi boşa harcaması gerçek bir maliyet.

**Devre kesici eklendi** (`sources/classify.kademe1_circuit_open`).
Kademe 1 son `CIRCUIT_BREAKER_FAILURE_THRESHOLD` (3) denemede hiç
başarı yoksa, `CIRCUIT_BREAKER_COOLDOWN_MINUTES` (30) dk boyunca
çağrıyı tamamen atlıyor (loglanmıyor) — kota geri geldiğinde bir
sonraki döngü otomatik olarak ücretsiz "prob" deniyor ve başarı olursa
devre kendiliğinden kapanıyor. Kalıcı bir engelleme değil, sadece
bilinen-tükenmiş bir kotaya karşı her döngüde tekrar tekrar 68s
harcamayı önlüyor. Devre kesicinin gerçekten çalıştığı `ai_call_log`
zaman damgalarıyla doğrulandı: devreye girmeden önce ~15 dk'da bir,
girdikten sonra ~45 dk'da bir deneme (30 dk soğuma + döngü aralığı).

**stderr kayıp sorunu bulundu ve düzeltildi.** Kademe 2'de gerçek bir
başarısızlık patlaması (%61'e düşüş, art arda ~10 hata, "non-zero exit,
boş stderr") araştırılırken ortaya çıktı: zamanlanmış görev
`WshShell.Run` ile başlatıldığı için başlattığı sürecin stderr'i hiçbir
yere gitmiyordu — her `[uyarı]` mesajı (Kademe 1/2/3 hataları dahil)
sessizce kayboluyordu, `ai_call_log`'un kendi kısaltılmış stderr
özetinden başka hiçbir iz kalmıyordu. İki parçalı düzeltme: (1)
`analysis.py`/`classify.py`'nin hata mesajları artık stderr boşsa
stdout'a düşüyor (`register-task.ps1`'i yeniden çalıştırmadan da işe
yarar), (2) `register-task.ps1` artık `cmd /c ... 2>>data\observer-stderr.log`
üzerinden çalışıyor, böylece tüm `[uyarı]` mesajları kalıcı olarak
yakalanıyor (mevcut zamanlanmış görev bunu almak için yeniden
kaydedilmeli: `.\scripts\register-task.ps1`).

**Pencere sorunu büyük ölçüde çözüldü** (4 denemeden sonra), ama **tam
sıfır değil** — bu ayrım önemli, o yüzden ikisini ayrı tutuyoruz. Gerçek
neden: `hermes.exe` kendi içinde ayrı bir `conhost.exe` ve kendi Python
yorumlayıcısını başlatıyordu — dıştaki çağrıya uygulanan
`CREATE_NO_WINDOW`/`STARTUPINFO` bunu kapsamıyordu. Çözüm:
`sources/_hidden_subprocess.py`'nin `run_hidden_and_reap()`'i her
çağrıdan sonra **tüm süreç ağacını** (`taskkill /F /T`) zorla temizliyor;
zamanlanmış görev de artık `wscript.exe` üzerinden tamamen gizli
çalışıyor (`scripts/register-task.ps1`). Bu, kalıcı/tekrar-tekrar-açılan
pencere sorununu (ana problem) gerçekten çözdü — süreç ağacı her seferinde
temiz kapanıyor, canlı doğrulandı.

**Kalan iz: kısa bir yanıp-sönme, ara sıra.** 2026-09-24'te kullanıcı
hâlâ ara sıra kısa bir pencere flaşı bildirdi (kalıcı değil, tekrar
tekrar açılıp kapanmıyor — tek karelik bir görünüp kaybolma). Neden:
`_WindowHider` pencereleri **poll ederek** gizliyor (0.1s aralıkla) —
bu, pencere oluşumuyla yarışan bir mekanizma, taskkill'in verdiği "süreç
ağacı temiz" garantisinden farklı bir şey ("hiçbir karede görünmedi"
garantisi değil). Poll aralığı 0.02s'ye düşürüldü (5 kat), bu riski
büyük ölçüde azaltıyor ama matematiksel olarak sıfırlamıyor — gerçek bir
sıfırlama bir Windows event hook'u (`SetWinEventHook`, pencere
oluşumuna polling değil tepki verir) gerektirir, şu an için orantısız
bir karmaşıklık (devre kesici sayesinde Kademe 1 çağrıları zaten ~45
dk'da bire indi, yani flaş de aynı oranda seyrekleşti).

**Gerçek üretim hatası bulundu ve düzeltildi.** `signal.py`'nin
`_NEGATIVE_NEWS_KEYWORDS` listesindeki tek başına `"hack"` kelimesi,
gerçek bir haberdeki "Hack VC" (bir girişim sermayesi şirketi) ismiyle
yanlışlıkla eşleşip saatlerce `accumulation` sinyallerini bastırmış —
`status.py` ile yapılan eleştirel bir inceleme sırasında bulundu.

**Huobi/HTX kapatıldı (deferred değil, structural exclusion).** Üçüncü
pass'te Huobi'nin kendi resmi imzalı proof-of-reserves listesi bulundu
(DefiLlama → github.com/huobiapi/Tool-Node.js-VerifyAddress) — otoritesi
önceki iki denemenin (etiket taraması, FUNDED BY zinciri) çok üstünde.
Listedeki 3 Ethereum adresinin hepsi canlı USDT/USDC bakiyesi için
kontrol edildi: **üçü de 0 USDT, 0 USDC.** Huobi'nin gerçek stablecoin
hacmi neredeyse tamamen TRON (TRC20) üzerinden akıyor — bu proje sadece
Ethereum mainnet taradığı için (`onchain.py`), Huobi'nin kendi resmi
kaynağı bile bu projenin izleyebileceği bir şey olmadığını doğruladı.
Zincir kapsamı genişlemedikçe yeniden açılmayacak.

**Aşama 5 iskeleti eklendi** (`approval.py`). Section 8'in "yarı
otomatik: küçük gerçek parayla, her işlemi kullanıcı onaylar" satırının
kod karşılığı — ama **hiçbir aşamada işlem yürütmüyor**, "Kritik sınır"
burada da kategorik. Bir Kademe 3 önerisi, Risk Guard'ı geçtikten sonra
(paper trading'e ek olarak, onun yerine değil — `ready_for_asama5`
ölçümü kapanan pozisyonların sürmesine bağlı) bir `approval_requests`
satırı olarak kaydediliyor: durum hep `pending` başlıyor, yalnızca
`python -m whale_tracker.approval approve/reject <id>` ile insan eliyle
kararlaştırılıyor. İki bağımsız kapı var, ikisi de tutmalı: kod
tarafında `ASAMA5_ENABLED` (varsayılan kapalı, açmak bilinçli bir
commit gerektiriyor) ve `evaluation.ready_for_asama5` (planın kendi
istatistiksel eşiği). "Onaylandı" durumu bile yalnızca "kullanıcının
kendi ayrı, onaylı bot/script'i artık işlem yapabilir" demek —
buradaki hiçbir kod borsa API'sine dokunmuyor. `ready_for_asama5` henüz
gerçek veriyle dolmadığı için bu tamamen bir iskelet, üretimde şu an
etkisiz (`ASAMA5_ENABLED = False`).

**Sıradaki:** İlk gerçek kağıt pozisyonların açılıp kapanmasını bekleme
(Kademe 3 "strong" eşiğine ulaşan aday nadir).

| Aşama | Durum |
|---|---|
| 1. Gözlemci | ✅ tamamlandı, zamanlanmış çalışıyor |
| 2. Sinyal üretici | ✅ 5 sinyal + Kademe 2 derin analiz + Kademe 3 kağıt öneri, gerçek veriyle doğrulanmadı henüz |
| 3. Paper trading | ✅ kod tamam, simülasyonla doğrulandı, gerçek pozisyon henüz açılmadı (Kademe 3 eşiği nadir) |
| 4. Değerlendirme | ✅ ölçüm altyapısı hazır, simülasyonla doğrulandı, henüz yeterli gerçek kapanmış pozisyon yok |
| 5. Yarı otomatik (onaylı) | ✅ kod iskeleti hazır (`approval.py`), `ASAMA5_ENABLED=False` — üretimde etkisiz, `ready_for_asama5` gerçek veriyle dolunca açılabilir |
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
