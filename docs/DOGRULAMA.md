# Doğrulama · 21 Ekim 2026

Linux ortamında Python 3.12.14, Node 24.19.0 ve sistem Chromium'u ile doğrulandı.

- `python3 -m unittest discover -s tests -v`: **17/17 geçti**.
- `node --check web/app.js`: geçti.
- `python3 tests/ui_smoke.py`: 10 görünüm; müşteri oluşturma/arama/kart açılışı; kalemli KDV hesaplayan proforma oluşturma ve yazdırılabilir belge; geçmişe dayalı öneri; tamamlanan servisin seçili parçadan stok düşümü; randevu oluşturma; gerçek SQLite yedeği indirme. **Geçti, JavaScript hatası yok.**
- 1440, 1100 ve 390 piksel genişlikte ana ekranda sayfa taşması kontrol edildi.
- Uygulamanın gerçek `desktop.py --headless` başlatıcısı `.data` altında çalıştırıldı. Oturum çereziyle API isteği **200** döndü; müşteri/servis/stok tablolarının boş başladığı doğrulandı. Demo verileri bu alana eklenmedi.
- Veritabanı yedeği yeniden açılıp stok/cari değerleri ve `PRAGMA integrity_check` kontrol edildi.
- Yerel HTTP katmanında oturumsuz okuma ve başka kaynaktan yazma reddi test edildi.

## Henüz doğrulanmayanlar

- Windows üzerinde PyInstaller derlemesi, gerçek `.exe` açılışı, WebView2 pencere, yazdırma ve dosya indirme davranışı.
- GitHub Actions iş akışı çalıştırılmadı; Windows derlemesi elle başlatılmalıdır.
- Kurulum taslağına `start_skill` kaydedildi; ortamın yayımlanması ve yeni görevde geri yüklenmesi doğrulanmadı.

`genel-bakis.png` ve `proforma.png` ekran görüntüleri geçici demo veritabanından alınmıştır; gerçek işletme verisi içermez.
