# Sonuç: WT-EDGE-01 — 72 saatlik stablecoin akışı (ön kayıt 2026-09-26)

Ön kayıt: `2026-09-26-wt-edge-01-72h-stablecoin-flow.md` (commit `1877297`,
2026-09-26 04:50 UTC — test verisi indirilmeden önce). O belge değiştirilmedi.

Çalıştırma: `python -m whale_tracker.backtest --days 180 --end 2025-09-20
--db data/backtest-edge01.db`, kod `1877297` (dönem 2025-03-24 → 2025-09-20),
kullanıcının makinesinde, 2026-09-26.

## Deneme geçmişi (ön kayıttaki "yeniden çalıştırma" kuralı gereği)

Tamamlanan tek çalıştırma aşağıdaki sonuçtur. Ondan önceki denemelerin hiçbiri
zincir üstü veri indirmedi ve hiçbiri IC ya da başka bir sonuç üretmedi:

1. Yanlış dal (`master`, `0baa0e0`) + RPC anahtarı yerine yer tutucu metin →
   arşiv erişim kontrolünde durdu.
2. Doğru kod (`1877297`), anahtar değişkeni yine yer tutucu → aynı noktada durdu.
3. Aynı; yapılandırma hatası (HTTP 401 / varsayılan publicnode 403) → aynı
   noktada durdu.

Bu denemeler yalnızca fiyat/funding/Fear&Greed ham verisini önbelleğe aldı;
sonucu etkileyecek hiçbir şey görülmedi.

## Birincil test → **H1 DESTEKLENMEDİ**

| | IC (birikim sinyali) | tek yönlü `p_negative` |
|---|---|---|
| BTCUSDT 72s | −0.070 | 0.166 |

Kural: IC < 0 **ve** `p_negative` < 0.05. IC negatif (H1 yönünde) ama
p = 0.166 → kural karşılanmıyor.

## Doğrulayıcı (yalnızca yön)

| | IC | `p_negative` |
|---|---|---|
| ETHUSDT 72s | −0.076 | 0.158 |

Yön H1 ile tutarlı; ön kayıt gereği birincil sonucu değiştirmez.

## Bağlam (karar vermez)

| | IC | `p_negative` |
|---|---|---|
| BTCUSDT 24s | −0.025 | 0.334 |
| ETHUSDT 24s | −0.092 | 0.030 |

ETH 24s'in tek başına p < 0.05 çıkması, dört ölçümden birinin şansla bu
eşiği geçmesinin beklenen bir olayıdır ve ön kayıtta karar vermeyen bir
ölçümdür. Bundan yeni bir hipotez çıkarmak, bu turu doğuran hatayı (ikincil
sonuçtan hipotez kurmak) tekrarlamak olur.

Aşama 4 skor kartı (yeni maliyet modeli ve %1 hesap riski boyutlamasıyla):
134 kapanan pozisyon, strateji +%12.87 ↔ BTC-hold +%36.44 (geçmiyor);
işlem başına +%0.667 ↔ rastgele giriş +%0.896 ± 0.749 (p = 0.548).

## Üç dönemin birlikte okunması

Yeni akış tanımıyla ölçülen yalnızca bu dönemdir; önceki iki dönem kurumları
da sayan eski tanımla ölçülmüştü, bu yüzden sayılar birebir karşılaştırılamaz.
Yine de bugüne kadarki tüm IC'ler (üç dönem, iki ufuk, iki sembol) negatif
işaretli: borsaya giren stablecoin, sonraki getiriyle **zayıf pozitif**
ilişkili görünüyor. Ama hiçbir ön kayıtlı birincil test bunu anlamlı
bulmadı. Tutarlı ama küçük bir etki (|IC| ≲ 0.1), 180 günlük bir dönemde bu
testin ayırt edebileceği büyüklüğün (72s için |IC| ≳ 0.26) çok altında.

## Karar (ön kayıttaki kurala göre)

- **72 saatlik stablecoin akışının kanıtlanmış bir kenarı yoktur.** 24 saatlik
  hipotezle aynı yere düşer.
- `signal.py`'nin akış yorumu **tersine çevrilmez**; bu veri üretim
  sinyalini değiştirme gerekçesi değildir.
- Aşama 5 kapalı kalır.
- Canlı ileri test yine de ön kayıttaki gibi (canlı veri 180 güne ulaşınca,
  ≈ 2027-03-25) kayıt amacıyla bir kez çalıştırılır.
- Bundan sonrası için seçenekler (her biri yeni bir ön kayıt gerektirir,
  bu dosya hiçbirini seçmez): sinyali bırakmak; daha güçlü bir test
  tasarlamak (ör. birden çok dönemi önceden birleştiren tek bir test —
  gücü artırmanın eşik gevşetmeden tek meşru yolu); ya da akışı başka bir
  biçimde yeniden tanımlamak.
