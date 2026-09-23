# Teknik Yaklaşım (Gözlemci Aşaması) — kodlamadan önce

2026-09-23. Amaç: nasıl geliştireceğimize karar vermek, henüz kod yazmamak.

## Açık sorular ve bulduklarım

### 1. Bilinen borsa cüzdan adreslerini nereden alacağız?

**Güncelleme (2026-09-23, doğrulama sonrası) — ilk cevap yanlıştı, düzeltildi.**
`dawsbot/eth-labels`'ı önerdikten sonra gerçek veriyi indirip kontrol ettim
(144k satırlık `accounts.csv`). Sonuç: **kullanışlı değil, en azından
"binance" için.** "binance" geçen 5102 kayıt neredeyse tamamı yanlış
pozitifti — başka platformların (Bilaxy, Alameda Research vb.) Binance'e
para yatıran KENDİ kullanıcı cüzdanları, Binance'in kendi cüzdanları değil.
Gerçek `label` alanında yalnızca "binance-charity" (34 kayıt) vardı, ana
borsa cüzdanları hiç yoktu.

**Gerçek kaynak: Etherscan'in kendi resmi etiket sayfaları**
(`etherscan.io/accounts/label/<slug>`), doğrudan çekilip tek tek
doğrulandı. Sonuç `data/known-exchange-wallets.json`'da:

- **Binance, Bitfinex, Gemini**: temiz, küçük (6-7 adres) ana cüzdan
  listeleri — doğrudan kullanılabilir.
- **Coinbase**: web aramasıyla bulundu (Coinbase 1/23/44), ama tek bir
  temiz etiket sayfası yok — daha eksik, ileride tamamlanmalı.
- **Kraken**: **farklı bir yapı.** Etiket sayfası binlerce ayrı
  "Kraken Dep: 0x..." kullanıcı-başına-depozito adresi döndürüyor (78.727
  toplam), Binance gibi küçük bir ana-cüzdan seti değil. Bu borsa için
  akış takibi farklı bir yaklaşım gerektiriyor — şimdilik ertelendi.
- **OKX, Bybit**: label cloud'da bulunan girdiler ("okx-labs",
  "bybit-exploit") ana cüzdanları temsil etmiyor gibi görünüyor,
  doğrulanmadı, dahil edilmedi.

**Ders:** Bir borsa adını herhangi bir label/nameTag alanında substring
olarak aramak güvenilmez — başka platformların o borsaya giden kendi
depozito cüzdanlarını yanlış pozitif olarak yakalıyor. Her zaman birincil
kaynağa (Etherscan'in kendi etiket sayfası) karşı doğrulamak gerekiyor.
Tam liste ve bilinen tuzaklar `data/known-exchange-wallets.json`'da.

### 2. "Büyük transfer" eşiği ne olmalı?

Whale Alert'in kendi eşiklerini kamuya açık belgelerinde bulamadım — sadece
"kullanıcı tanımlar, minimum/maksimum yok" deniyor. **Bence bu aslında
doğru yaklaşım:** hazır bir sayıyı kopyalamak yerine, kendi backtest'imizle
kalibre etmeliyiz (tıpkı vdb projesindeki abstention-calibrate mantığı gibi
— sabit sayı değil, veriden türetilmiş eşik). Başlangıç için endüstri
sezgisiyle kaba bir aralık (~$1M+ tek işlem) ile başlayıp, birkaç haftalık
gerçek veri biriktikten sonra eşiği gözden geçiririz. Bunu bir "gün 1
kararı" olarak dondurmayacağız.

### 3. Token transferlerini (USDT/USDC) nasıl verimli izleriz?

`eth_getLogs`, kontrat adresine (USDT/USDC'nin sabit kontrat adresleri) ve
`Transfer` event imzasına filtrelenerek kullanılabilir — çoğu public RPC'de
ücretsiz, özel yapılandırma gerektirmiyor. Native ETH transferleri için
ayrı bir yol gerekiyor (her bloğun `tx.value` alanına bakmak, log değil).
**Önemli kısıtlama:** `eth_getLogs`'un genellikle diğer RPC metodlarından
daha sıkı hız limitleri var — blok aralığını küçük tutmamız ve WebSocket
abonelik (polling yerine push) kullanmayı değerlendirmemiz gerekebilir.

## Önerilen mimari

```
whale-tracker/
├── src/
│   └── whale_tracker/
│       ├── sources/          # Her veri kaynağı için ayrı, izole modül
│       │   ├── onchain.py    # publicnode RPC + eth-labels + eth_getLogs
│       │   ├── binance.py    # funding rate, OI, order book
│       │   ├── news.py       # RSS toplama
│       │   └── sentiment.py  # Fear&Greed + kendi haber sentiment'i
│       ├── storage.py        # SQLite - tek dosya, yerel, basit
│       ├── classify.py       # Kademe 1: ucuz model sınıflandırması
│       └── report.py         # Günlük/anlık rapor üretimi
├── data/                     # SQLite dosyası, .gitignore'da
├── tests/
└── pyproject.toml
```

**Neden bu şekilde:** `pmiri` ve `vdb` projelerindeki desenle tutarlı
(izole kaynak modülleri, tek-dosya yerel depolama, `uv`/`pyproject.toml`).
Her kaynak modülü bağımsız test edilebilir ve birbirinden habersiz — biri
çökerse diğerleri etkilenmez (vdb'nin "her format için ayrı parser, biri
hata verirse diğerleri etkilenmez" felsefesiyle aynı).

**Depolama:** SQLite — Brain-Eleven'in kendi StateStore'u, vdb'nin kendi
metadata katmanı, PMIRI'nin kendi backend'i hepsi SQLite kullanıyor. Bu
proje için de Qdrant/Postgres gibi ağır bir şey gerekmiyor; veri hacmi
(balina hareketleri + haberler) SQLite'ın rahatça kaldıracağı ölçekte.

**Kademe 0 (bu aşama) neyi YAPMAYACAK:** İşlem mantığı yok, sinyal
birleştirme yok, güven puanı yok. Sadece: topla, sınıflandır (önemli mi/
yönü ne), günlük özet raporu üret. Bu, planının kendi sıralamasına sadık
kalıyor.

## İlk somut kilometre taşı (öneri, henüz başlanmadı)

1. `sources/binance.py` — funding rate + OI + order book snapshot'ı çek,
   SQLite'a yaz. (Anahtarsız, hemen test edilebilir.)
2. `sources/sentiment.py` — Fear&Greed'i çek, SQLite'a yaz. (Anahtarsız.)
3. `sources/onchain.py` — eth-labels'tan Binance'in bilinen cüzdanlarını
   çek, publicnode RPC ile o cüzdanlara giren/çıkan son N bloktaki
   transferleri tara, eşik-üstü olanları SQLite'a yaz. (Anahtarsız ama
   teknik olarak en karmaşık parça — muhtemelen ilk denemede tam
   çalışmayabilir, iteratif geliştirilecek.)
4. `report.py` — üçünü birleştirip basit bir günlük özet üretir (henüz
   sinyal/karar yok, sadece "bugün ne oldu" raporu).

Bunların hiçbiri hesap açmayı gerektirmiyor. Haberler (RSS) ve daha geniş
zincir kapsamı (BSC, Polygon vb.) sonraki bir iterasyon.

## Senin kararını istediğim noktalar

- Bu mimari/sıra mantıklı mı, yoksa farklı bir yapı mı istersin?
- İlk kilometre taşı sırası (Binance → Fear&Greed → on-chain → rapor)
  uygun mu, yoksa on-chain'den mi başlamalıyız (asıl "balina" kısmı o)?
- Eşik kalibrasyonunu "şimdilik kaba tahmin, sonra veriyle düzelt" olarak
  bırakmak sana uygun mu?
