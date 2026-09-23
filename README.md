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

**Aşama: Gözlemci (1/6) — çalışıyor ve zamanlanmış.** Dört kaynak da uçtan
uca test edildi, gerçek veriyle: Binance piyasa verisi, Fear&Greed, haberler
(CoinDesk+Cointelegraph RSS), ve zincir üstü büyük USDT/USDC transferleri
(eşik-üstü, bilinen cüzdan/kurum/DEX/işaretlenmiş adreslerle çapraz
kontrollü, kategoriye göre gruplu rapor). İşlem mantığı yok, risk yok —
sadece topla + rapor et. Windows Task Scheduler'a kayıtlı, her 15 dakikada
bir otomatik çalışıyor (`data/observer.log`).

**Sıradaki:** Bilinen cüzdan listesini genişletmeye devam (hâlâ çoğu
transfer "bilinmeyen"), birkaç günlük gerçek log biriktirip gözden geçirme,
Kademe 1 (ucuz-model sınıflandırma) tasarımına başlama.

| Aşama | Durum |
|---|---|
| 1. Gözlemci | ✅ çalışıyor (genişletiliyor) |
| 2. Sinyal üretici | beklemede |
| 3. Paper trading | beklemede |
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
