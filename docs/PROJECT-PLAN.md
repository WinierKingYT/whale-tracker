# Proje Planı — AI Destekli Piyasa Okuma ve Balina Takip Sistemi

Ahmet'in orijinal konsept dokümanı, 2026-09-23. Bu dosya planı korur;
uygulama detayları ayrı belgelerde (`docs/DATA-SOURCES.md` vb.) tutulur.

## 1. Ana Amaç

Kripto piyasasını 7/24 izleyen, büyük oyuncuların (balinaların) hareketlerini,
haberleri ve piyasa yapısını birlikte okuyan, bunlardan anlamlı sinyaller
çıkaran ve disiplinli risk kurallarıyla pozisyon alan bir sistem kurmak.

Sistemin felsefesi: "Piyasayı tahmin etmeye çalışma; piyasada büyük paranın
ne yaptığını gör, bağlamını anla, riski kontrol ederek arkasından git."

## 2. Neden Balina Takibi?

Kriptoda fiyatı kısa-orta vadede büyük ölçüde büyük sermayeli oyuncular
hareket ettirir. Blockchain'in açık olması, bu oyuncuların cüzdan
hareketlerini herkesin görebilmesini sağlar. Hisse senedinde bu kadar
şeffaf veri yoktur; bu, kriptoya özgü bir avantajdır.

Dürüst olmak gerekirse: balina hareketleri tek başına güvenilir sinyal
değildir. Bir balinanın borsaya coin göndermesi satış demek olabilir, ama
teminat yatırma, başka cüzdana taşıma veya yanıltma amaçlı bir hareket de
olabilir. Balina verisi sistemin tek girdisi değil, en önemli girdilerinden
biri olacak.

## 3. Sinyal Kaynakları

**A. Zincir üstü balina hareketleri (on-chain)**
- Büyük cüzdanlardan borsalara giriş → olası satış baskısı
- Borsalardan soğuk cüzdanlara çıkış → biriktirme (olumlu)
- Stablecoin (USDT/USDC) borsalara büyük giriş → alım gücü hazırlanıyor
- Bilinen akıllı cüzdanların (geçmişte başarılı olmuş) alım/satımları
- Kaynaklar: Whale Alert, Arkham, Nansen, Etherscan/blockchain API'leri

**B. Borsa içi büyük oyuncu izleri**
- Emir defterinde büyük alım/satım duvarları (gerçek mi sahte mi)
- Ani hacim patlamaları
- Vadeli piyasada açık pozisyon (open interest) ve funding rate değişimleri
- Büyük likidasyon bölgeleri

**C. Haberler ve duygu durumu**
- Regülasyon, ETF, borsa listeleme/delist, hack, makro veriler
- Sosyal medya duygu durumu ve Korku/Açgözlülük endeksi

**D. Teknik piyasa yapısı**
- Trend yönü, destek/direnç, volatilite
- Piyasa rejimi: yükseliş trendi / yatay / düşüş / panik

## 4. Karar Mekanizması

Karar tek bir sinyalle değil, sinyallerin birbirini doğrulamasıyla verilir.

**Örnek:** Balinalar son 24 saatte borsalardan 5.000 BTC çekti (biriktirme) +
stablecoin girişi arttı + funding rate nötr + fiyat önemli bir desteğin
üstünde + olumsuz haber yok → Güçlü alım adayı.

**Karşı örnek:** Balina alımı var ama fiyat zaten %15 yükselmiş, funding çok
yüksek, herkes long → Girme, geç kalındı; ters tuzak riski var.

Her sinyale bir güven puanı verilir; toplam puan belirli bir eşiği geçmedikçe
işlem açılmaz.

## 5. AI'nin Rolü (Kademeli Yapı)

| Kademe | Görev | Araç | Sıklık |
|---|---|---|---|
| 0 | Veri toplama, göstergeler, risk kuralları | Kod | 7/24, ücretsiz |
| 1 | Her balina hareketini/haberi sınıflandırma: önemli mi, yönü ne, güvenilir mi | Ucuz model | 7/24, çok ucuz |
| 2 | Önemli durumları bağlamla birleştirip analiz | Claude Sonnet | Saatte birkaç kez |
| 3 | Nihai işlem önerisi, karşı argümanlar, en kötü senaryo | Claude Opus / Fable | Sadece karar anında |
| — | Onay / red / pozisyon küçültme | Risk Guard (kod) | Her işlemde, son söz |

## 6. İşlem Tarzı

- **Zaman dilimi:** Saatlik–günlük pozisyonlar (swing). Saniyelik
  scalping'de profesyonel botlarla yarışamayız.
- **Varlıklar:** Başlangıçta BTC ve ETH (likit, manipülasyonu daha zor),
  sonra büyük altcoinler.
- **Yön:** Başta sadece spot alım (long). Açığa satış ve kaldıraç ileride,
  ancak kanıtlanmış başarı sonrası.

## 7. Risk Kuralları (Değişmez Anayasa)

- İşlem başına maksimum risk: sermayenin %1'i
- Her işlemin mutlaka stop-loss'u olur
- Günlük maksimum kayıp: %3 → aşılırsa sistem o gün durur
- Aynı anda en fazla 2–3 açık pozisyon
- Kaldıraç yok
- API anahtarında para çekme izni yok
- Aylık AI bütçe tavanı; aşılırsa sistem sadece Kademe 0'da çalışır

## 8. Geliştirme Yol Haritası

1. **Gözlemci:** Balina hareketlerini, haberleri ve piyasayı toplayıp
   günlük/anlık rapor gönderir. İşlem yok. **← şu an burada.**
2. **Sinyal üretici:** "Burada alım fırsatı var, gerekçe şu" önerileri
   üretir ve kaydeder.
3. **Paper trading:** Önerileri sahte parayla uygular; birkaç hafta
   sonuçlar ölçülür.
4. **Değerlendirme:** Hangi sinyaller gerçekten işe yaradı? Zayıf olanlar
   atılır.
5. **Yarı otomatik:** Küçük gerçek parayla; her işlemi kullanıcı
   onaylar.
6. **Otomatik:** Sadece önceki aşamalar tutarlı başarı gösterirse.

## 9. Başarı Kriteri

Sistemin başarısı "çok para kazandı mı" ile değil, şunlarla ölçülür:

- Sinyallerin isabet oranı ve ortalama kazanç/kayıp oranı
- Maksimum düşüş (drawdown) kontrol altında mı?
- Aynı dönemde sadece BTC tutmaktan daha iyi mi?

Eğer "sadece BTC alıp beklemek" sistemi yeniyorsa, sistemi geliştirmeye
devam ederiz ama gerçek parayı artırmayız.
