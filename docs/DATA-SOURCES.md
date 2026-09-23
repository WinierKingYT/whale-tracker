# Veri Kaynakları Araştırması (Gözlemci Aşaması)

2026-09-23, web araştırmasıyla derlendi. Kaynaklar her bölümün altında.
**Hiçbir API anahtarı henüz yok** — bu doküman "ne ile başlayalım" kararını
vermek için.

## A. Zincir üstü balina hareketleri

| Kaynak | Ücretsiz mi? | Not |
|---|---|---|
| **Whale Alert** | **Hayır** | En bilinen ama ücretsiz katmanı yok. En ucuz plan $29.95/ay (WebSocket, saatte 100 uyarı). Enterprise $699/ay. |
| **Arkham Intelligence** | **Kısmen, evet** | Web platformu (adres arama, entity sayfaları, işlem izleme, temel uyarılar) tamamen ücretsiz. API de AWS Marketplace üzerinden kullanım-bazlı, düşük hacimde ücretsiz bir giriş katmanı var. **Önerilen başlangıç.** |
| **Etherscan (+ BscScan/Polygonscan)** | **Evet** | Ücretsiz API anahtarı: 5 istek/sn, günde 100.000 istek. Whale Alert'in yaptığını DIY yapmak mümkün — bilinen borsa cüzdan adreslerini izleyip eşik-üstü transferleri kendimiz filtreleriz. Temmuz 2026'dan itibaren ücretsiz katmanda sayfa başına max kayıt 10.000'den 1.000'e düşürüldü (bilinmesi gereken bir kısıtlama). |
| Nansen | Araştırılmadı | Bilinen ücretli bir alternatif; Arkham ücretsiz katmanı yeterli olursa gerek kalmayabilir. |

**Öneri:** Arkham'ın ücretsiz web/API katmanıyla başla; yetersiz kalırsa
Etherscan tabanlı DIY borsa-cüzdanı izleme ile tamamla. Whale Alert'in
$29.95/ay planı, Gözlemci kanıtlanmış fayda gösterirse ikinci aşamada
değerlendirilebilir.

Kaynaklar:
- [Whale Alert Pricing](https://developer.whale-alert.io/pricing.html)
- [Arkham Intel API](https://intel.arkm.com/api)
- [Arkham API Docs](https://docs.intel.arkm.com/openapi/portfolio/n/a)
- [Etherscan Rate Limits](https://docs.etherscan.io/etherscan-v2/rate-limits)
- [Etherscan Free Tier Changes (Temmuz 2026)](https://info.etherscan.com/whats-changing-in-the-free-api-tier-coverage-and-why/)

## B. Borsa içi piyasa yapısı (order book, OI, funding rate)

| Kaynak | Ücretsiz mi? | Not |
|---|---|---|
| **Binance Futures API** | **Evet** | Piyasa verisi endpoint'leri (funding rate geçmişi, open interest, order book, likidasyon) public — API anahtarı bile gerekmiyor. `GET /fapi/v1/fundingRate`, `GET /fapi/v1/openInterest`, `GET /futures/data/openInterestHist`. |

**Öneri:** Doğrudan Binance'in public futures API'siyle başla — tamamen
ücretsiz, anahtar gerekmiyor, en likit borsa.

Kaynak:
- [Binance Futures Market Data API](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)

## C. Haberler ve duygu durumu

| Kaynak | Ücretsiz mi? | Not |
|---|---|---|
| **Alternative.me Fear & Greed Index** | **Evet** | Uzun süredir standart, güvenilir, tamamen ücretsiz, anahtar gerekmiyor. |
| CryptoPanic | Kısmen | Ücretsiz katmanı var (limitli); yaygın kullanılan bir haber/sentiment agregatörü. |
| cryptocurrency.cv (GitHub, nirholas) | Evet (iddia) | Anahtar gerektirmeyen açık kaynak bir proje — **daha az bilinen, doğrulanmadan güvenilmemeli.** Değerlendirilebilir ama birincil kaynak olarak değil. |

**Öneri:** Alternative.me ile başla (kanıtlanmış, sıfır risk). CryptoPanic'i
ikinci kaynak olarak ekle. `cryptocurrency.cv`'yi şüpheyle değerlendir —
küçük, az bilinen bir proje, veri kalitesi/sürekliliği doğrulanmadı.

Kaynak:
- [Alternative.me Fear & Greed Index](https://alternative.me/crypto/fear-and-greed-index/)

## Özet: Gözlemci için ilk entegrasyon sırası

1. **Binance Futures public API** — anahtar gerektirmiyor, hemen başlanabilir.
2. **Alternative.me Fear & Greed Index** — anahtar gerektirmiyor, hemen başlanabilir.
3. **Arkham** — ücretsiz hesap açılması gerekiyor, ardından API/web erişimi.
4. **Etherscan** — ücretsiz API anahtarı alınması gerekiyor (dakikalar sürer).

İlk ikisi hiçbir hesap açmadan bugün kodlanabilir. 3 ve 4 için Ahmet'in
ücretsiz hesap açması gerekiyor (Claude hesap açamaz — kimlik/e-posta
doğrulaması gerektiren adımlar kullanıcının kendisi tarafından yapılmalı).
