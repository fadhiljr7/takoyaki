# Nodepay AI Bot
Bot otomatis untuk menggunakan proxy Nodepay AI.

## Langkah Instalasi
1. **Clone repository**
   ```bash
   git clone https://github.com/fadhiljr7/takoyaki.git
   cd takoyaki
   ```

2. **Install dependencies**

   Install paket yang diperlukan dari file `requirements.txt`:
   ```bash
   pip install -r requirements.txt
   ```

4. **Ambil Token Nodepay**
   - Buka [dashboard Nodepay](https://app.nodepay.ai/dashboard) Anda.
   - Buka *inspect element* dengan menekan `Ctrl + Shift + I`.
   - Pergi ke tab `Application` lalu expand `Local storage` lalu klik `http://app.nodepay.ai`
   - Anda akan menemukan key np_token sebagai token anda
   - Simpan token anda pada file `Token.txt`.

5. **Konfigurasi Proxy**

   Isi daftar proxy pada file `Proxiy.txt` menggunakan Connection type `Hostname` menggunakan format berikut:
   ```
   username:password@hostname:port
   ```
   Tambahkan satu baris untuk setiap proxy yang ingin digunakan.

7. **Jalankan Bot**

   Untuk menjalankan bot, gunakan perintah berikut:
   ```bash
   python mufiiin.py
   ```
   Jika kamu tidak memiliki premium residential proxy maka jalankan:
   
   ```bash
   python autofin.py
   ```

## Catatan
Pastikan proxy yang digunakan valid dan sesuai format agar bot dapat berjalan dengan lancar.
Python Version:3.10++
