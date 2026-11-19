# Tubes PCD Kelompok 6 — Segmentasi Banjir Sentinel-1 Demak

Proyek Tugas Besar Pengolahan Citra Digital (PCD) Kelompok 6: Ekstraksi, pra-pengolahan, dan segmentasi citra SAR Sentinel-1 pada wilayah terdampak bencana banjir di Kabupaten Demak (Kecamatan Karanganyar & Gajah), Jawa Tengah, dengan mask referensi air MNDWI dari citra multispektral Sentinel-2.

---

## 👥 Anggota Kelompok (Kelompok 6)

1. **Afriza Choirie Saputra**
2. **Muhamad Dino Dermawan**
3. **Rizki Nurmahmudi**

---

## 📝 Deskripsi Proyek

Proyek ini bertujuan untuk mengolah citra satelit SAR Sentinel-1 GRD polarisasi VV (dalam satuan desibel/dB) untuk mendeteksi dan memantau dinamika banjir di wilayah Demak pada Maret 2024. Dataset mencakup kondisi pra-banjir (median Januari 2024) serta empat fase kejadian banjir (15, 19, 27, dan 31 Maret 2024).

Sebagai ground truth / referensi segmentasi air, digunakan citra Sentinel-2 L2A dengan tutupan awan <20% dan masking awan Scene Classification Layer (SCL) terdekat dalam rentang $\pm 10$ hari dari tanggal banjir, yang diproses menggunakan indeks air **MNDWI** (Modified Normalized Difference Water Index):
$$\text{MNDWI} = \frac{\text{B3 (Green)} - \text{B11 (SWIR1)}}{\text{B3 (Green)} + \text{B11 (SWIR1)}} > 0$$

> [!IMPORTANT]
> **Catatan Pengelolaan Dataset di Repositori Git:**
> File dataset biner (citra GeoTIFF `.tif` dan hasil konversi PNG `.png`) **TIDAK di-commit ke repositori GitHub** karena ukuran file yang sangat besar. Repositori ini hanya melacak kode sumber (scripts), file konfigurasi/dependensi, dan file `dataset/metadata.csv`.
> Seluruh citra diekspor langsung ke **Google Drive** (folder `dataset_demak_tubes`) dan harus diunduh dari sana, **bukan di-clone dari repository**.

---

## 📁 Struktur Direktori

```text
Tubes/
├── .gitignore               # Mengabaikan file biner dataset (.tif, .png), cache, venv
├── requirements.txt         # Daftar pustaka Python yang dibutuhkan
├── README.md                # Dokumentasi proyek & panduan penggunaan
├── export_dataset_gee.py    # SCRIPT 1: Export citra dari GEE ke Google Drive
├── convert_dataset.py       # SCRIPT 2: Konversi GeoTIFF ke PNG & generate metadata
├── export_manifest.csv      # Manifest task export GEE (dibuat lokal oleh Script 1)
└── dataset/                 # Folder lokal untuk menampung hasil unduhan Google Drive
    ├── s1_preflood/         # Citra S1 pra-banjir (Januari 2024 median, descending)
    ├── s1_flood_20240315/   # Citra S1 banjir 15 Mar 2024 (descending, orbit 76)
    ├── s1_flood_20240319/   # Citra S1 banjir 19 Mar 2024 (ascending, orbit 127)
    ├── s1_flood_20240327/   # Citra S1 banjir 27 Mar 2024 (descending, orbit 76)
    ├── s1_flood_20240331/   # Citra S1 banjir 31 Mar 2024 (ascending, orbit 127)
    ├── masks_mndwi/         # Mask referensi air MNDWI dari Sentinel-2
    └── metadata.csv         # Metadata lengkap seluruh chip (dibuat oleh Script 2)
```

---

## ⚙️ Persiapan & Instalasi

### 1. Install Dependensi Python
Jalankan perintah berikut di terminal:
```bash
pip install -r requirements.txt
```

Pustaka yang diinstal:
- `earthengine-api`: Google Earth Engine Python Client
- `rasterio`: Pembacaan data spasial GeoTIFF & bounding box koordinat
- `numpy`: Komputasi array numerik
- `pandas`: Pengelolaan tabel metadata dan CSV
- `Pillow`: Pemrosesan dan penyimpanan citra PNG 8-bit

### 2. Autentikasi Google Earth Engine Pertama Kali
Earth Engine memerlukan akun Google yang telah terdaftar di [Google Earth Engine](https://earthengine.google.com/).

Jalankan perintah autentikasi di terminal:
```bash
earthengine authenticate
```
Atau jalankan `export_dataset_gee.py` langsung, script akan otomatis memanggil `ee.Authenticate()` jika sesi belum ditemukan:
1. Browser akan terbuka untuk meminta login Google dan izin akses Earth Engine.
2. Selesaikan alur OAuth di browser.
3. **Catatan Google Cloud Project**: Jika akun Anda meminta Google Cloud Project ID, tentukan project ID Anda pada variabel `GEE_PROJECT` di awal file `export_dataset_gee.py` (misal: `GEE_PROJECT = 'nama-project-anda'`).

---

## 🚀 Alur Kerja Menjalankan Script

### LANGKAH 1 — Menjalankan Export di Earth Engine (Script 1)
Jalankan script pertama:
```bash
python export_dataset_gee.py
```
**Tugas script ini:**
1. Memverifikasi koneksi dan autentikasi Earth Engine.
2. Membentuk grid 6 kolom $\times$ 5 baris (30 lokasi chip) berukuran $256 \times 256$ piksel @ 10 m ($2,56 \times 2,56\text{ km}$) dengan jangkar sudut barat laut ROI `[110.68, -6.90, 110.82, -6.79]`.
3. Mengambil citra Sentinel-1 (VV, float dB apa adanya):
   - Pra-banjir: Komposit median Januari 2024, descending
   - 15 Maret 2024, descending (orbit 76)
   - 19 Maret 2024, ascending (orbit 127)
   - 27 Maret 2024, descending (orbit 76)
   - 31 Maret 2024, ascending (orbit 127)
4. Mengambil citra Sentinel-2 L2A terdekat ($\pm 10$ hari, tutupan awan <20%, filter SCL) dan menghitung mask air MNDWI $> 0$. Jika tidak ada citra yang memenuhi syarat, dicatat sebagai `'tanpa referensi'` dan lanjut tanpa mask.
5. Mendaftarkan total 150 tasks export Sentinel-1 (30 chip $\times$ 5 tanggal) + tasks mask MNDWI ke Google Drive pada folder `'dataset_demak_tubes'`.
6. Menyimpan daftar tugas ke `export_manifest.csv`.
7. **PENTING**: Script ini **tidak melakukan download**. Tugas dieksekusi di cloud Earth Engine. Pantau status tugas di: [https://code.earthengine.google.com/tasks](https://code.earthengine.google.com/tasks).

---

### LANGKAH 2 — Unduh File dari Google Drive ke Komputer
1. Buka [Google Drive](https://drive.google.com/).
2. Temukan folder bernama `dataset_demak_tubes`.
3. Setelah semua tugas selesai di GEE (status *Completed*), unduh folder tersebut ke laptop.
4. Pindahkan dan ekstrak seluruh file `.tif` ke dalam folder `dataset/` di direktori proyek ini.
   *(Jika file diletakkan langsung di `dataset/`, Script 2 memiliki fitur auto-organizer yang otomatis memilah file ke subfolder masing-masing).*

---

### LANGKAH 3 — Konversi Dataset ke PNG & Metadata (Script 2)
Setelah file GeoTIFF berada di folder `dataset/`, jalankan script kedua:
```bash
python convert_dataset.py
```
**Tugas script ini:**
1. Membaca file GeoTIFF dari subfolder `s1_preflood/`, `s1_flood_20240315/`, `s1_flood_20240319/`, `s1_flood_20240327/`, `s1_flood_20240331/`, dan `masks_mndwi/`.
2. **Citra S1**: Memotong nilai ke $[-30, 0]\text{ dB}$, melakukan penskalaan linear ke $[0, 255]$, dan menyimpannya sebagai PNG 8-bit dengan nama yang sama di folder yang sama.
3. **Mask MNDWI**: Mengubah nilai $0/1$ menjadi $0/255$ dan menyimpannya sebagai PNG 8-bit.
4. Menghitung proporsi air (fraksi piksel bernilai 1 pada mask) per chip.
5. Menulis tabel `dataset/metadata.csv` berisi:
   - `chip_id`: ID chip (misal: `r02_c03`)
   - `row`, `col`: Indeks baris (0–4) dan kolom (0–5)
   - `tanggal`: Tanggal citra (`20240101`, `20240315`, dst.)
   - `jenis`: `preflood` atau `flood`
   - `file_s1`: Nama file citra Sentinel-1
   - `file_mask`: Nama file mask MNDWI (atau kosong jika tanpa referensi)
   - `proporsi_air`: Fraksi piksel air ($0.0 - 1.0$)
   - `min_lon`, `min_lat`, `max_lon`, `max_lat`: Batas koordinat spasial
6. Menampilkan ringkasan statistik dataset dan **Top 5 chip dengan proporsi genangan air tertinggi**.
7. Pemrosesan dilakukan secara *streaming* satu per satu chip sehingga penggunaan memori RAM sangat rendah (< 100 MB, aman untuk RAM 8 GB).

---

## 📊 Spesifikasi Teknis Dataset

| Parameter | Spesifikasi |
|---|---|
| **Wilayah (ROI)** | Kec. Karanganyar & Gajah, Kab. Demak `[110.68, -6.90, 110.82, -6.79]` |
| **Grid Lokasi** | 6 kolom $\times$ 5 baris = 30 chip lokasi |
| **Dimensi Tiap Chip** | $256 \times 256$ piksel pada skala 10 m ($2,56 \times 2,56\text{ km}$) |
| **Sensor Utama** | Sentinel-1 GRD IW, polarisasi VV (nilai dB) |
| **Tanggal S1** | Pra-banjir (Jan 2024 median desc), 15 Mar 2024 (desc orbit 76), 19 Mar 2024 (asc orbit 127), 27 Mar 2024 (desc orbit 76), 31 Mar 2024 (asc orbit 127) |
| **Sensor Referensi** | Sentinel-2 L2A (S2_SR_HARMONIZED), awan <20%, filter SCL |
| **Indeks Air** | MNDWI $= (\text{B3} - \text{B11}) / (\text{B3} + \text{B11}) > 0$ |
| **Format Asli** | GeoTIFF float (S1 dB) & Byte (Mask 0/1) |
| **Format Siap Pakai** | PNG 8-bit Grayscale $[0, 255]$ & `dataset/metadata.csv` |
