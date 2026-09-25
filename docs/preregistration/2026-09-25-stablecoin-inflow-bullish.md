# Ön kayıt: borsaya stablecoin girişi yükseliş işaretidir

**Kayıt tarihi:** 2026-09-25, test verisi indirilmeden ÖNCE. Bu dosyanın ilk
commit'i test dönemine ait zincir üstü veriyi çeken ilk çalıştırmadan önce
yapıldı; git geçmişi bunun kanıtı. Sonuç ne çıkarsa çıksın, bu belge
sonradan değiştirilmez — sonuç ayrı bir bölüm/dosya olarak eklenir.

## Neden

180 günlük backtest (2026-03-28 → 2026-09-24, `python -m whale_tracker.backtest
--days 180`) projenin mevcut varsayımını desteklemedi: `signal.py`, bilinen
borsa cüzdanlarına **net stablecoin girişini** "dağıtım / satış baskısı",
net çıkışı "birikim" sayıyor. Ölçülen dört bilgi katsayısının (IC) dördü de
ters yöndeydi (BTC 24s -0.035, BTC 72s -0.045, ETH 24s -0.033, ETH 72s
-0.086), hiçbiri tek başına anlamlı değildi. Zincir üstü analizde yaygın
yorum da bunun tersi: borsaya giren stablecoin, BTC/ETH almak için bekleyen
alım gücüdür.

Bu yön o 180 günü gördükten SONRA fark edildi. Aynı veride hem hipotez
kurup hem doğrulamak kendini kandırmak olur; bu yüzden hipotez burada
sabitleniyor ve hiç bakılmamış bir dönemde test ediliyor.

## Hipotez (H1)

24 saatlik net stablecoin girişi (USDT+USDC, bilinen ve DEX/işaretli
olmayan cüzdanlara giren eksi çıkan — `signal._aggregate_exchange_flow` ile
aynı kural) **ne kadar yüksekse**, sonraki 24 saatlik BTC getirisi o kadar
yüksektir.

`backtest/signal_ic.py` birikim sinyalini (= net ÇIKIŞ) raporladığı için H1
orada **negatif IC** olarak görünür.

## Birincil test (karar yalnızca buna bağlı)

- **Sembol / ufuk:** BTCUSDT, 24 saat (96 döngü).
- **İstatistik:** `information_coefficient(db, "BTCUSDT", horizon_cycles=96)`
  — Spearman IC, varsayılan `trials=500`, `seed=0`.
- **p-değeri:** tek yönlü, `p_negative` (dairesel kaydırmalı null
  dağılımında gözlenen IC kadar ya da daha negatif olanların oranı).
- **Eşik:** α = 0.05.
- **H1 desteklenir ⇔** IC < 0 **ve** `p_negative` < 0.05.

## İkincil ölçümler (raporlanır, karar vermez)

BTCUSDT 72s, ETHUSDT 24s ve 72s IC'leri; rastgele giriş karşılaştırması;
Aşama 4 skor kartı. BTC ve ETH birbirine çok bağlı olduğu için bunlar
bağımsız kanıt sayılmaz ve birincil sonucu "kurtarmak" için kullanılmaz.

## Test dönemi

`python -m whale_tracker.backtest --days 180 --end 2026-03-24` → 2025-09-25 →
2026-03-24. Daha önce incelenen dönemin zincir üstü ısınma verisi ve fiyat
serisi 2026-03-27'de başlıyordu; 3 günlük boşluk sayesinde IC'ye giren akış
ve ileri getiri verisi iki dönem arasında hiç örtüşmez. (Önceki dönemin
destek/direnç hesabı günlük mumlarla Şubat sonuna uzanıyordu, ama bunlar
IC hesabına girmez.) Kod, eşikler ve cüzdan listesi bu commit'teki hâliyle
kullanılır.

## Karar kuralı

- **H1 desteklenirse:** yön değişikliği (`signal.py`'nin akış yorumunu ve
  Kademe 1 sınıflandırma istemini tersine çevirmek) gerçek bir aday olur —
  ama ancak ayrı bir değişiklik olarak, yeni yön için yeniden ölçülerek.
  Tek başına Aşama 5'i açmaz.
- **H1 desteklenmezse:** 24 saatlik net stablecoin akışının iki yönde de
  kanıtlanmış bir kenarı yoktur. Yön ters çevrilmez; sinyal ya başka bir
  biçimde (ör. akış büyüklüğüne eşik, farklı pencere) yeniden
  tasarlanır — o da yeni bir ön kayıtla — ya da bırakılır.

## Bilinen sınırlamalar (önceden kabul edilir)

- Güç: 180 günde 24s ufukta yalnızca |IC| ≳ 0.15 güvenilir ayırt edilir;
  küçük gerçek bir etki "desteklenmedi" çıkabilir.
- Cüzdan listesi 2026-09 tarihli; bir yıl önce farklı sıcak cüzdanlar
  kullanılmış olabilir (hayatta kalan yanlılığı, önceki dönemden daha büyük).
- Backtest'in diğer sınırlamaları (`backtest/run.py` LIMITATIONS) aynen
  geçerlidir.
