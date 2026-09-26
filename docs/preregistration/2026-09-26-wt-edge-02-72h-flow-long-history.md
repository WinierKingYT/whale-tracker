# Ön kayıt: WT-EDGE-02 — 72 saatlik stablecoin akışı, uzun geçmiş testi

**Kayıt tarihi:** 2026-09-26, test verisi indirilmeden ÖNCE. Bu dosyanın ilk
commit'i test dönemine ait zincir üstü veriyi çeken ilk çalıştırmadan önce
yapıldı; git geçmişi bunun kanıtı. Sonuç ne çıkarsa çıksın bu belge sonradan
değiştirilmez; sonuç ayrı bir `.RESULT.md` dosyası olarak eklenir.

## Neden

WT-EDGE-01 (`2026-09-26-wt-edge-01-72h-stablecoin-flow.RESULT.md`) H1'i
desteklemedi: BTC 72s IC −0.070, p = 0.166. Sorun büyük ihtimalle **güç**:
180 günde yalnızca ~59 bağımsız 72s pencere var ve test ancak |IC| ≳ 0.26'yı
ayırt edebiliyordu. Oysa bugüne kadarki tüm ölçümler (farklı tanım ve
dönemlerle) |IC| ≈ 0.03–0.10 civarında, hep aynı işaretle çıktı.

Eşik gevşetmeden gücü artırmanın tek meşru yolu daha fazla, **hiç
bakılmamış** veri. 2025-03-24 öncesi zincir üstü akışa bu projede hiç
bakılmadı. Bu test o dönemi kullanır.

Bu belge WT-EDGE-01'in "sonrası için seçenekler" bölümündeki "daha güçlü bir
test tasarlamak" seçeneğidir. Hipotez, tanım, ufuk ve karar kuralı
WT-EDGE-01 ile birebir aynıdır; değişen **yalnızca test dönemi ve uzunluğu**.

## Hipotez (H1): WT-EDGE-01 ile aynı

Bilinen borsa cüzdanlarına (yalnızca `entity_type == "exchange"`,
`whale_tracker/flow.py`) 24 saatlik **net stablecoin girişi** (USDT+USDC,
giren eksi çıkan) ne kadar yüksekse, sonraki **72 saatlik BTC getirisi** o
kadar yüksektir. `signal_ic.py`'nin raporladığı birikim sinyalinde bu
**negatif IC** olarak görünür.

## Birincil test (karar yalnızca buna bağlı)

- **Sembol / ufuk:** BTCUSDT, 72 saat (288 döngü).
- **İstatistik:** `information_coefficient(db, "BTCUSDT", horizon_cycles=288)`:
  Spearman IC, `trials=500`, `seed=0`.
- **p-değeri:** tek yönlü `p_negative` (dairesel kaydırmalı null).
- **Eşik:** α = 0.05, tek birincil test.
- **H1 desteklenir ⇔** IC < 0 **ve** `p_negative` < 0.05.

Ufuk bilerek 72s bırakıldı. 24s'e geçmek, önceki sonuçlara bakarak ufuk
seçmek olurdu. Kaba güç hesabı (IC × √pencere) da 72s'i öne koyuyor:
beklenen |IC| ≈ 0.07 ve ~265 pencereyle ≈ 1.1, 24s'te |IC| ≈ 0.03 ve ~800
pencereyle ≈ 0.85.

## İkincil / doğrulayıcı (raporlanır, birincili değiştirmez)

- **ETHUSDT 72s:** yalnızca yön (IC < 0 mı?). BTC başarısızken ETH'nin
  anlamlı çıkması H1'i kurtarmaz.
- **Alt dönem tutarlılığı (yalnızca rapor):** dönem iki yarıya bölünüp her
  yarının BTC 72s IC işareti raporlanır. Karar vermez; etkinin tek bir
  dönemden gelip gelmediğini göstermek içindir.
- BTC/ETH 24s IC'leri, rastgele giriş karşılaştırması ve Aşama 4 skor kartı
  yalnızca bağlamdır.

## Test dönemi (hiç bakılmamış veri)

```
python -m whale_tracker.backtest --days 800 --end 2025-03-15 --db data/backtest-edge02.db
```

→ 2023-01-05 → 2025-03-15 (≈ 26 ay). Daha önce kullanılan dönemler:

| Dönem | Kullanım |
|---|---|
| 2026-03-28 → 2026-09-24 | keşif |
| 2025-09-25 → 2026-03-24 | 24s ön kaydı, 72s ipucunun kaynağı |
| 2025-03-24 → 2025-09-20 | WT-EDGE-01 |
| **2023-01-05 → 2025-03-15** | **bu test, ilk kez indirilecek** |

Son 72s ileri getirisi 2025-03-18'de biter. WT-EDGE-01'in akış ısınması
2025-03-23'te başladığı için dönemler hiç örtüşmez.

Kod, eşikler, maliyet modeli ve cüzdan listesi bu commit'teki hâliyle
kullanılır. Test **bir kez** çalıştırılır. Yalnızca veri indirme ya da
yapılandırma hatasında (RPC kesintisi, kota, anahtar) yeniden çalıştırılır.
Bu durumda indirilen parçalar önbellekten devam eder ve deneme sonuç
dosyasına yazılır. Kısmi bir çalıştırmanın IC çıktısı görülürse, o çıktı
sonuç sayılır.

## Karar kuralı

- **H1 desteklenmezse:** 26 aylık, yeterli güçteki bir testte de etki yok
  demektir. Stablecoin akış sinyali **bırakılır**: `signal.py`'de akış
  bileşeninin rolü ayrı bir değişiklikle küçültülür ya da kaldırılır, yeni
  bir sinyal araştırması başka bir ön kayıtla açılır. Canlı ileri test
  kayıt amacıyla yine çalıştırılır.
- **H1 desteklenirse:** akışın yönü (giriş = yükseliş) **aday** olur.
  `signal.py`'nin akış yorumu ayrı bir değişiklikle tersine çevrilir. Yeni
  yöndeki strateji maliyet dahil rastgele giriş testine karşı ayrıca ölçülür
  ve canlı veride izlenir. Tek başına Aşama 5'i açmaz; Aşama 5 kendi
  kapılarından (`ready_for_asama5` + `ASAMA5_ENABLED`) geçmek zorundadır.

## Bilinen sınırlamalar (önceden kabul edilir)

- **Hayatta kalan yanlılığı artık daha büyük:** cüzdan listesi 2026-09
  tarihli. 2023'te borsaların farklı sıcak cüzdanlar kullanmış olması
  muhtemel, akış eksik ölçülebilir. Bu, IC'yi sıfıra doğru çeker. Yani
  testi zorlaştırır, sahte pozitif üretmez.
- **BUSD dönemi:** 2023'ün başında Binance'in stablecoin akışının önemli
  bir kısmı BUSD'deydi ve bu kod yalnızca USDT/USDC izliyor. Etkisi yine
  sıfıra doğru.
- **Rejim farkı:** 2023–2024 (ETF öncesi/sonrası) ile bugünkü piyasa
  yapısı farklı olabilir; geçmişte var olan bir etki bugün geçerli
  olmayabilir. Bu yüzden olumlu sonuç bile yalnızca "aday"dır.
- **Kota:** ~275 zincir üstü parça indirilecek; Alchemy ücretsiz planın
  aylık kotası yetmeyebilir. Kota hatası yapılandırma hatası sayılır.
- Backtest'in diğer sınırlamaları (`backtest/run.py` LIMITATIONS) aynen
  geçerlidir.
