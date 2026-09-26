# Ön kayıt: WT-EDGE-01 — 72 saatlik stablecoin akışı doğrulaması

**Kayıt tarihi:** 2026-09-26, test verisi indirilmeden ÖNCE. Bu dosyanın ilk
commit'i test dönemine ait zincir üstü veriyi çeken ilk çalıştırmadan önce
yapıldı; git geçmişi bunun kanıtı. Sonuç ne çıkarsa çıksın bu belge sonradan
değiştirilmez; sonuç ayrı bir `.RESULT.md` dosyası olarak eklenir.

## Neden

Önceki ön kayıt (`2026-09-25-stablecoin-inflow-bullish.md`) 24 saatlik
hipotezi test etti ve **desteklemedi** (BTC 24s IC -0.027, p = 0.240).
Aynı çalıştırmanın ikincil ölçümlerinde 72 saatlik ufuk öne çıktı (BTC 72s
IC -0.099, p = 0.010; ETH 72s IC -0.091, p = 0.018).

Bu 72s hipotezi o sonuçları GÖRDÜKTEN SONRA kuruldu. O yüzden o iki dönemde
kanıt sayılamaz. Burada sabitlenip, hipotezi kurarken kullanılmamış bir
dönemde ve canlı ileri veride test ediliyor.

## Önceki sonuçlardan bu yana değişen ölçüm (WT-05.1, PR #1)

Önceki tüm IC'ler, `notable_non_exchange_entities` altındaki kurumları
(ör. Abraxas Capital) borsa akışı sayan eski tanımla hesaplandı. Bu test
**yeni tanımla** yapılır: yalnızca `entity_type == "exchange"` olan
cüzdanlar (`whale_tracker/flow.py`). Yani 72s ipucu bile bu tanımla hiç
ölçülmedi; bu test onun için de ilk temiz ölçümdür.

## Hipotez (H1)

Bilinen borsa cüzdanlarına (yalnızca `exchange` tipi) 24 saatlik **net
stablecoin girişi** (USDT+USDC, giren eksi çıkan) **ne kadar yüksekse**,
sonraki **72 saatlik BTC getirisi** o kadar yüksektir.

`backtest/signal_ic.py` birikim sinyalini (= net ÇIKIŞ = −net giriş)
raporladığı için H1 orada **negatif IC** olarak görünür.

Akış penceresi 24 saat kalır (`FLOW_WINDOW_HOURS`); değişen yalnızca ufuk.
Pencere ya da eşik bu testte ayarlanmaz.

## Birincil test (karar yalnızca buna bağlı)

- **Sembol / ufuk:** BTCUSDT, 72 saat (288 döngü).
- **İstatistik:** `information_coefficient(db, "BTCUSDT", horizon_cycles=288)`:
  Spearman IC, `trials=500`, `seed=0` (varsayılanlar).
- **p-değeri:** tek yönlü `p_negative` (dairesel kaydırmalı null
  dağılımında gözlenen IC kadar ya da daha negatif olanların oranı). 72s
  getiriler üst üste bindiği için bağımsız-örnek varsayan bir test
  kullanılmaz; dairesel kaydırma otokorelasyonu korur.
- **Eşik:** α = 0.05, tek test, çoklu karşılaştırma düzeltmesi gerekmez
  (tek birincil test).
- **H1 desteklenir ⇔** IC < 0 **ve** `p_negative` < 0.05.

## İkincil / doğrulayıcı (raporlanır, birincili değiştirmez)

- **ETHUSDT 72s:** yalnızca yön tutarlılığı: IC < 0 mu? BTC ile çok
  yüksek korelasyonlu olduğu için bağımsız kanıt sayılmaz; BTC başarısızken
  ETH'nin anlamlı çıkması H1'i **kurtarmaz**.
- BTC/ETH 24s IC'leri, rastgele giriş karşılaştırması, Aşama 4 skor kartı
  (yeni yürütme maliyet modeliyle) yalnızca bağlam olarak raporlanır.

## Test dönemi (hiç bakılmamış veri)

```
python -m whale_tracker.backtest --days 180 --end 2025-09-20 --db data/backtest-edge01.db
```

→ 2025-03-24 → 2025-09-20. Daha önce kullanılan dönemler:

| Dönem | Kullanım |
|---|---|
| 2026-03-28 → 2026-09-24 | keşif (ilk 180g backtest) |
| 2025-09-25 → 2026-03-24 | 24s ön kaydının test dönemi, 72s ipucunun kaynağı |
| **2025-03-24 → 2025-09-20** | **bu test, ilk kez indirilecek** |

Zincir üstü ısınma verisi başlangıçtan 1 gün önce başlar (2025-03-23); son
72s ileri getirisi dönemin sonuna (2025-09-20) kadar olan fiyatla sınırlı.
Sonraki dönemin akış ısınması 2025-09-24'te başladığından IC'ye giren akış ve
getiri verisi hiçbir dönemle örtüşmez.

Kod, eşikler, maliyet modeli ve cüzdan listesi bu commit'teki hâliyle
kullanılır. Test **bir kez** çalıştırılır. Veri indirme hatası dışında
(ör. RPC kesintisi) yeniden çalıştırılmaz; yeniden çalıştırılırsa nedeni
sonuç dosyasına yazılır.

## Canlı ileri test (ikinci, bağımsız aşama)

Geçmiş test ne çıkarsa çıksın, canlı gözlemcinin topladığı veri bu commit
tarihinden itibaren ayrı bir ileri örneklemdir. **Canlı veri 180 güne
ulaştığında** (≈ 2027-03-25) aynı birincil test, aynı kod ve eşikle, yalnızca
bu tarihten sonraki canlı veri üzerinde bir kez çalıştırılır. Ara bakışlar
raporlanabilir ama karar vermez.

## Karar kuralı

- **Geçmiş test H1'i desteklemezse:** 72s hipotezi 24s ile aynı yere
  düşer: akışın iki yönde de kanıtlanmış bir kenarı yok. Yön ters
  çevrilmez; sinyal ya yeni bir ön kayıtla yeniden tasarlanır ya da
  bırakılır. Canlı ileri test yine de kayıt amacıyla çalıştırılır.
- **Geçmiş test H1'i desteklerse:** bu, **aday** bir kenardır, üretim
  sinyali değildir. `signal.py`'nin akış yorumunun tersine çevrilmesi
  ancak **canlı ileri test de** H1'i desteklerse ayrı bir değişiklik olarak
  yapılır. Tek başına Aşama 5'i açmaz.
- **İkisi de desteklerse:** yön değişikliği yapılır; ardından yeni yöndeki
  strateji, maliyet dahil rastgele giriş testine karşı ayrıca ölçülür.

## Bilinen sınırlamalar (önceden kabul edilir)

- **Güç:** 180 günde yalnızca ~60 bağımsız 72s dilim vardır; |IC| ≈ 0.1
  büyüklüğündeki gerçek bir etki bile "desteklenmedi" çıkabilir. Bu, eşik
  gevşetmenin gerekçesi değildir.
- **Hayatta kalan yanlılığı:** cüzdan listesi 2026-09 tarihli; 2025
  ortasında farklı sıcak cüzdanlar kullanılmış olabilir (önceki dönemlerden
  daha büyük risk). Akış eksik ölçülürse IC sıfıra doğru çekilir.
- Backtest'in diğer sınırlamaları (`backtest/run.py` LIMITATIONS) aynen
  geçerlidir.
