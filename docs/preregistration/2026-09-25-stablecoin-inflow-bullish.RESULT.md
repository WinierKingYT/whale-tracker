# Sonuç: borsaya stablecoin girişi yükseliş işaretidir (ön kayıt 2026-09-25)

Ön kayıt: `2026-09-25-stablecoin-inflow-bullish.md` (commit `e3a4993`, 2026-09-25
20:17:58 +0300 — test verisi indirilmeden önce). O belge değiştirilmedi.

Çalıştırma: `python -m whale_tracker.backtest --days 180 --end 2026-03-24
--db data/backtest-prereg.db` (dönem 2025-09-25 → 2026-03-24).

## Birincil test → **H1 DESTEKLENMEDİ**

| | IC (birikim sinyali) | tek yönlü `p_negative` |
|---|---|---|
| BTCUSDT 24s | -0.027 | 0.240 |

Kural: IC < 0 **ve** `p_negative` < 0.05. IC negatif ama p = 0.240 → kural
karşılanmıyor. Ön kayıttaki karar kuralı gereği sinyalin yönü **ters
çevrilmez**; 24 saatlik net stablecoin akışının bu testte iki yönde de
kanıtlanmış bir kenarı yoktur.

## İkincil ölçümler (karar vermez, raporlanır)

| | IC | `p_negative` |
|---|---|---|
| BTCUSDT 72s | -0.099 | 0.010 |
| ETHUSDT 24s | -0.028 | 0.222 |
| ETHUSDT 72s | -0.091 | 0.018 |

Keşif dönemiyle (2026-03-28 → 09-24: -0.035, -0.045, -0.033, -0.086)
birlikte 8 IC'nin 8'i de negatif; 72 saatlik ufuk bu dönemde tek başına
anlamlı. Bu, birincil testi kurtarmaz. En fazla, **yeni** bir ön kayıtla ve
bu iki dönemin dışındaki veride (ör. 2025-03 → 2025-09 ya da canlı ileriye
dönük veri) test edilebilecek bir 72s hipotezi önerir. BTC ve ETH çok yüksek
korelasyonlu olduğundan bu 4+4 ölçüm bağımsız kanıt değildir.

## Yan bulgu: Aşama 5 kapısı düşüş piyasasında yanlış "hazır" diyor

Bu dönemde BTC-hold -%34.69, strateji -%0.95 → `beats_btc_hold` = true →
`ready_for_asama5` = true. Oysa strateji para kaybetti (120 işlem, %41.7
isabet) ve işlem başına getirisi (-%0.80) aynı dönemdeki rastgele
girişlerden (-%0.64 ± 0.78, p = 0.58) ayırt edilemiyor. Kapı, sermayesinin
çoğu nakitte duran bir stratejiyi %100 BTC pozisyonuyla kıyaslıyor; her
düşüş piyasasında beceri olmadan geçilir. `ASAMA5_ENABLED = False` olduğu
için şu an etkisiz, ama gerçek paradan önce düzeltilmeli (ör. maruziyet
eşleştirilmiş kıyas ya da rastgele giriş testine karşı kenar şartı).
