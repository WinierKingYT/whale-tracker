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

**Aşama: Gözlemci tamamlandı (1/6), Sinyal üretici başladı (2/6).**
Dört kaynak uçtan uca test edildi ve zamanlanmış çalışıyor (Windows Task
Scheduler, 15 dakikada bir, `data/observer.log`): Binance piyasa verisi,
Fear&Greed, haberler (CoinDesk+Cointelegraph RSS), zincir üstü büyük
USDT/USDC transferleri (bilinen cüzdan/kurum/DEX/işaretlenmiş adreslerle
çapraz kontrollü). Kademe 1 (Hermes ile en büyük olayların ucuz
sınıflandırması) çalışıyor. Sinyal üretici ilk hali çalışıyor: 24s net
borsa akışı + funding + Fear&Greed + haber taraması, birbirini doğrulayan
skorlu adaylar üretiyor (`signal.py`) — **ama teknik/destek-direnç sinyali
henüz yok, bu yüzden her aday 0.75 güven tavanında dondurulmuş, dürüstçe
belirtiliyor.** Hâlâ işlem yok, risk yok.

**Sıradaki:** Birkaç günlük gerçek sinyal-aday verisi biriktirip gözden
geçirme; teknik/destek-direnç sinyalini eklemek (Aşama D, henüz yok);
bilinen cüzdan listesini genişletmeye devam.

| Aşama | Durum |
|---|---|
| 1. Gözlemci | ✅ tamamlandı, zamanlanmış çalışıyor |
| 2. Sinyal üretici | 🚧 ilk hali çalışıyor (teknik sinyal eksik) |
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
