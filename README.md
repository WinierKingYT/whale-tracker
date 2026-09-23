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

**Sıradaki:** İlk kağıt pozisyonların açılıp kapanmasını bekleme (Kademe 3
"strong" eşiğine ulaşan aday nadir, henüz gerçek pozisyon açılmadı);
bilinen cüzdan listesini genişletmeye devam (Huobi/HTX hâlâ açık); Aşama 4
(Değerlendirme — isabet oranı, P&L, BTC-hold karşılaştırması) için yeterli
kapanmış pozisyon birikince tasarım.

| Aşama | Durum |
|---|---|
| 1. Gözlemci | ✅ tamamlandı, zamanlanmış çalışıyor |
| 2. Sinyal üretici | ✅ 5 sinyal + Kademe 2 derin analiz + Kademe 3 kağıt öneri, gerçek veriyle doğrulanmadı henüz |
| 3. Paper trading | ✅ kod tamam, ilk pozisyon henüz açılmadı (Kademe 3 eşiği nadir) |
| 4. Değerlendirme | beklemede |
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
