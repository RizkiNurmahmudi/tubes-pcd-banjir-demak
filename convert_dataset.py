#!/usr/bin/env python3
"""
=============================================================================
Tubes Pengolahan Citra Digital (PCD) Kelompok 6
Dataset Banjir Demak (Kecamatan Karanganyar & Gajah, Kab. Demak)
SCRIPT 2: convert_dataset.py

Deskripsi:
Script ini dijalankan SETELAH semua file GeoTIFF dari Google Drive diunduh ke
folder lokal 'dataset/'. Script memproses konversi citra dan mask:
1. Citra Sentinel-1 (VV, float dB):
   - Dipotong (clip) ke rentang [-30, 0] dB.
   - Diskalakan secara linear ke 0-255 (uint8).
   - Disimpan sebagai PNG 8-bit (grayscale) dengan nama yang sama (.tif -> .png)
     di folder yang sama.
2. Mask referensi MNDWI:
   - Nilai biner 0/1 diubah menjadi 0/255 (uint8).
   - Disimpan sebagai PNG 8-bit dengan nama yang sama di folder yang sama.
3. Menghitung proporsi air per chip (fraksi piksel bernilai 1 pada mask).
4. Menyimpan ringkasan metadata lengkap ke dataset/metadata.csv:
   Kolom: chip_id, row, col, tanggal, jenis (preflood/flood), file_s1, file_mask,
          proporsi_air, min_lon, min_lat, max_lon, max_lat.
5. Mencetak ringkasan:
   - Jumlah file per tanggal
   - Jumlah mask yang ada vs hilang
   - 5 chip dengan proporsi air tertinggi
6. Hemat memori (proses satu chip per satu waktu, aman untuk laptop RAM 8 GB).
=============================================================================
"""

import os
import sys
import re
import math
import shutil
import pandas as pd
import numpy as np
from pathlib import Path
from PIL import Image

# =============================================================================
# KONFIGURASI DIREKTORI & PROYEK
# =============================================================================
# PROJECT_DIR: Direktori proyek utama. Dapat diubah jika lokasi kerja berbeda.
PROJECT_DIR = Path(__file__).resolve().parent

# Direktori utama dataset
DATASET_DIR = PROJECT_DIR / "dataset"

# Subfolder dataset sesuai spesifikasi
S1_PREFLOOD_DIR = DATASET_DIR / "s1_preflood"
S1_FLOOD_DIRS = {
    "20240315": DATASET_DIR / "s1_flood_20240315",
    "20240319": DATASET_DIR / "s1_flood_20240319",
    "20240327": DATASET_DIR / "s1_flood_20240327",
    "20240331": DATASET_DIR / "s1_flood_20240331",
}
MASKS_DIR = DATASET_DIR / "masks_mndwi"

ALL_TARGET_DIRS = [
    S1_PREFLOOD_DIR,
    S1_FLOOD_DIRS["20240315"],
    S1_FLOOD_DIRS["20240319"],
    S1_FLOOD_DIRS["20240327"],
    S1_FLOOD_DIRS["20240331"],
    MASKS_DIR,
]

# ROI Grid reference jika bounds GeoTIFF perlu dihitung ulang
WEST = 110.68
NORTH = -6.79
CHIP_SIZE_M = 2560.0


def calculate_chip_bounds_from_id(row: int, col: int):
    """
    Menghitung batas koordinat WGS84 untuk chip berdasarkan baris dan kolom.
    Digunakan sebagai fallback jika GeoTIFF tidak menyertakan affine transform.
    """
    lat_ref_rad = math.radians(NORTH)
    m_per_deg_lat = (
        111132.92
        - 559.82 * math.cos(2 * lat_ref_rad)
        + 1.175 * math.cos(4 * lat_ref_rad)
    )
    a = 6378137.0
    e2 = 0.00669437999014
    m_per_deg_lon = (
        (math.pi / 180.0)
        * a
        * math.cos(lat_ref_rad)
        / math.sqrt(1.0 - e2 * (math.sin(lat_ref_rad) ** 2))
    )
    d_lat = CHIP_SIZE_M / m_per_deg_lat
    d_lon = CHIP_SIZE_M / m_per_deg_lon

    min_lon = WEST + col * d_lon
    max_lon = WEST + (col + 1) * d_lon
    max_lat = NORTH - row * d_lat
    min_lat = NORTH - (row + 1) * d_lat
    return min_lon, min_lat, max_lon, max_lat


def auto_organize_raw_downloads():
    """
    Fitur pembantu otomatis:
    Jika pengguna mengunduh folder 'dataset_demak_tubes' dari Google Drive
    dan menaruh semua file GeoTIFF langsung di folder dataset/ (flat),
    fungsi ini akan otomatis memilah dan memindahkan file ke subfolder yang sesuai.
    """
    # Buat seluruh subfolder target
    for d in ALL_TARGET_DIRS:
        d.mkdir(parents=True, exist_ok=True)

    # Sumber file yang dicek: DATASET_DIR dan DATASET_DIR / 'dataset_demak_tubes'
    search_dirs = [DATASET_DIR]
    drive_folder = DATASET_DIR / "dataset_demak_tubes"
    if drive_folder.exists() and drive_folder.is_dir():
        search_dirs.append(drive_folder)

    moved_count = 0
    for s_dir in search_dirs:
        for item in s_dir.glob("*.tif"):
            fname = item.name
            target_dir = None

            if "mask" in fname:
                target_dir = MASKS_DIR
            elif "20240101" in fname or "preflood" in fname:
                target_dir = S1_PREFLOOD_DIR
            elif "20240315" in fname:
                target_dir = S1_FLOOD_DIRS["20240315"]
            elif "20240319" in fname:
                target_dir = S1_FLOOD_DIRS["20240319"]
            elif "20240327" in fname:
                target_dir = S1_FLOOD_DIRS["20240327"]
            elif "20240331" in fname:
                target_dir = S1_FLOOD_DIRS["20240331"]

            if target_dir and item.parent != target_dir:
                dest = target_dir / fname
                if not dest.exists():
                    shutil.move(str(item), str(dest))
                    moved_count += 1

    if moved_count > 0:
        print(f"[INFO] Auto-organizer: Memindahkan {moved_count} file GeoTIFF ke subfolder yang sesuai.")


def read_geotiff_data_and_bounds(file_path: Path, fallback_row: int = 0, fallback_col: int = 0):
    """
    Membaca data citra dan bounding box (min_lon, min_lat, max_lon, max_lat).
    Menggunakan rasterio jika tersedia, dengan fallback tifffile / PIL.
    """
    data = None
    bounds = None

    # Opsi 1: Coba gunakan rasterio
    try:
        import rasterio
        with rasterio.open(file_path) as src:
            data = src.read(1)
            b = src.bounds
            # Validasi jika bounds memiliki nilai koordinat wajar
            if abs(b.left) > 0.0001 or abs(b.right) > 0.0001:
                bounds = (float(b.left), float(b.bottom), float(b.right), float(b.top))
    except ImportError:
        pass
    except Exception as e:
        print(f"[WARN] Gagal membaca dengan rasterio ({e}), mencoba fallback...")

    # Opsi 2: Fallback tifffile jika data belum terbaca
    if data is None:
        try:
            import tifffile
            data = tifffile.imread(str(file_path))
            if data.ndim > 2:
                data = data[0]
        except Exception:
            pass

    # Opsi 3: Fallback Pillow jika data belum terbaca
    if data is None:
        with Image.open(file_path) as im:
            data = np.array(im, dtype=np.float32)

    # Jika bounds belum diperoleh dari header GeoTIFF, gunakan hitungan grid WGS84
    if bounds is None:
        bounds = calculate_chip_bounds_from_id(fallback_row, fallback_col)

    return data, bounds


def convert_s1_image(tif_path: Path, fallback_row: int, fallback_col: int):
    """
    Mengonversi citra Sentinel-1 (dB, float):
    - Potong (clip) ke rentang [-30, 0] dB.
    - Skala linear ke 0-255 (uint8).
    - Simpan sebagai PNG 8-bit (mode L) di folder yang sama.
    - Kembalikan bounding box (min_lon, min_lat, max_lon, max_lat).
    """
    data, bounds = read_geotiff_data_and_bounds(tif_path, fallback_row, fallback_col)

    # Tangani NaN / Inf jika ada
    data = np.nan_to_num(data, nan=-30.0, posinf=0.0, neginf=-30.0)

    # 1. Clip nilai ke [-30, 0] dB
    clipped = np.clip(data, -30.0, 0.0)

    # 2. Skala linear ke [0, 255]
    # Nilai -30 dB -> 0, Nilai 0 dB -> 255
    scaled = np.round((clipped + 30.0) / 30.0 * 255.0)
    uint8_img = np.clip(scaled, 0, 255).astype(np.uint8)

    # 3. Simpan sebagai PNG 8-bit di folder yang sama
    png_path = tif_path.with_suffix(".png")
    img = Image.fromarray(uint8_img, mode="L")
    img.save(png_path)

    # Hapus array dari memori secara eksplisit
    del data, clipped, scaled, uint8_img

    return bounds


def convert_mask_image(tif_path: Path, fallback_row: int, fallback_col: int):
    """
    Mengonversi mask referensi MNDWI:
    - Nilai 0/1 menjadi 0/255 uint8.
    - Simpan sebagai PNG 8-bit di folder yang sama.
    - Hitung proporsi air (fraksi piksel bernilai 1).
    """
    data, _ = read_geotiff_data_and_bounds(tif_path, fallback_row, fallback_col)

    # Tangani NaN jika ada
    data = np.nan_to_num(data, nan=0.0)

    # Hitung proporsi air (fraksi piksel bernilai 1 / piksel air)
    water_pixels = np.count_nonzero(data > 0)
    total_pixels = data.size
    proporsi_air = float(water_pixels / total_pixels) if total_pixels > 0 else 0.0

    # Nilai 0/1 menjadi 0/255 uint8
    mask_uint8 = np.where(data > 0, 255, 0).astype(np.uint8)

    # Simpan PNG 8-bit
    png_path = tif_path.with_suffix(".png")
    img = Image.fromarray(mask_uint8, mode="L")
    img.save(png_path)

    del data, mask_uint8

    return proporsi_air


def parse_filename(filename: str):
    """
    Mengekstrak informasi chip_id, row, col, tanggal, tipe dari nama file.
    Pola nama: chip_r{rr}_c{cc}_{YYYYMMDD}_{tipe}.tif
    Contoh: chip_r02_c03_20240315_VV.tif
    """
    pattern = r"^chip_r(\d{2})_c(\d{2})_([a-zA-Z0-9]+)_([a-zA-Z0-9]+)\.(tif|tiff)$"
    match = re.match(pattern, filename, re.IGNORECASE)
    if match:
        row = int(match.group(1))
        col = int(match.group(2))
        chip_id = f"r{row:02d}_c{col:02d}"
        date_str = match.group(3)
        tipe = match.group(4)
        return chip_id, row, col, date_str, tipe
    return None, None, None, None, None


def main():
    print("=" * 70)
    print("TUBES PCD KELOMPOK 6 - KONVERSI DATASET BANJIR DEMAK")
    print(f"Direktori Proyek (PROJECT_DIR) : {PROJECT_DIR}")
    print(f"Direktori Dataset (DATASET_DIR): {DATASET_DIR}")
    print("=" * 70)

    if not DATASET_DIR.exists():
        print(f"\n[ERROR] Folder dataset tidak ditemukan di: {DATASET_DIR}")
        print("Silakan unduh hasil export dari Google Drive ke folder tersebut terlebih dahulu.")
        sys.exit(1)

    # 1. Jalankan pembantu auto-organize jika file masih berada langsung di dataset/
    auto_organize_raw_downloads()

    # 2. Proses Seluruh Mask MNDWI terlebih dahulu
    print("\n[1/3] Mengonversi mask MNDWI ke PNG 8-bit & menghitung proporsi air...")
    mask_files = sorted(list(MASKS_DIR.glob("*.tif")))
    print(f"Ditemukan {len(mask_files)} file mask di {MASKS_DIR.name}/.")

    # Dictionary untuk menyimpan proporsi air: (chip_id, tanggal) -> (proporsi_air, mask_filename)
    masks_info = {}

    for mf in mask_files:
        chip_id, row, col, date_str, _ = parse_filename(mf.name)
        if chip_id is None:
            continue

        prop = convert_mask_image(mf, fallback_row=row, fallback_col=col)
        masks_info[(chip_id, date_str)] = {
            "proporsi_air": prop,
            "file_mask": mf.name,
        }

    print(f"✓ Selesai mengonversi {len(masks_info)} mask MNDWI.")

    # 3. Proses Citra Sentinel-1 (VV) di tiap subfolder
    print("\n[2/3] Mengonversi citra Sentinel-1 (VV, [-30, 0] dB -> [0, 255] PNG)...")

    metadata_rows = []
    file_counts = {
        "20240101 (preflood)": 0,
        "20240315 (flood)": 0,
        "20240319 (flood)": 0,
        "20240327 (flood)": 0,
        "20240331 (flood)": 0,
    }

    s1_folder_mapping = [
        (S1_PREFLOOD_DIR, "preflood", "20240101 (preflood)"),
        (S1_FLOOD_DIRS["20240315"], "flood", "20240315 (flood)"),
        (S1_FLOOD_DIRS["20240319"], "flood", "20240319 (flood)"),
        (S1_FLOOD_DIRS["20240327"], "flood", "20240327 (flood)"),
        (S1_FLOOD_DIRS["20240331"], "flood", "20240331 (flood)"),
    ]

    total_s1_converted = 0

    for folder, jenis, label in s1_folder_mapping:
        if not folder.exists():
            continue

        tif_list = sorted(list(folder.glob("*.tif")))
        print(f"  Memproses {folder.name} ({len(tif_list)} GeoTIFF)...")

        for s1_file in tif_list:
            chip_id, row, col, date_str, _ = parse_filename(s1_file.name)
            if chip_id is None:
                continue

            # Konversi satu per satu (hemat memori)
            bounds = convert_s1_image(s1_file, fallback_row=row, fallback_col=col)
            min_lon, min_lat, max_lon, max_lat = bounds

            # Cek ketersediaan mask untuk chip & tanggal ini
            mask_entry = masks_info.get((chip_id, date_str))
            if mask_entry is not None:
                prop_air = mask_entry["proporsi_air"]
                file_mask = mask_entry["file_mask"]
            else:
                prop_air = None
                file_mask = ""

            metadata_rows.append({
                "chip_id": chip_id,
                "row": row,
                "col": col,
                "tanggal": date_str,
                "jenis": jenis,
                "file_s1": s1_file.name,
                "file_mask": file_mask,
                "proporsi_air": round(prop_air, 4) if prop_air is not None else "",
                "min_lon": f"{min_lon:.6f}",
                "min_lat": f"{min_lat:.6f}",
                "max_lon": f"{max_lon:.6f}",
                "max_lat": f"{max_lat:.6f}",
            })

            file_counts[label] += 1
            total_s1_converted += 1

    print(f"✓ Selesai mengonversi total {total_s1_converted} citra Sentinel-1.")

    # 4. Tulis dataset/metadata.csv
    print("\n[3/3] Menulis dataset/metadata.csv...")
    metadata_df = pd.DataFrame(metadata_rows)
    metadata_path = DATASET_DIR / "metadata.csv"
    metadata_df.to_csv(metadata_path, index=False, encoding="utf-8")
    print(f"✓ Metadata tersimpan di: {metadata_path} ({len(metadata_df)} baris)")

    # 5. Ringkasan Hasil
    print("\n" + "=" * 70)
    print("RINGKASAN DATASET & HASIL KONVERSI")
    print("=" * 70)

    print("\n[A] Jumlah File S1 per Tanggal:")
    print("-" * 45)
    for tgl_label, count in file_counts.items():
        print(f"  - {tgl_label:<25}: {count} file GeoTIFF & PNG")
    print(f"  Total Citra S1 Diproses    : {total_s1_converted} file")

    print("\n[B] Status Ketersediaan Mask MNDWI:")
    print("-" * 45)
    total_flood_chips = sum(
        count for k, count in file_counts.items() if "flood" in k and "preflood" not in k
    )
    masks_available = len(masks_info)
    masks_missing = max(0, total_flood_chips - masks_available)
    print(f"  - Total Chip Banjir Harapan : {total_flood_chips} chip (30 chip x 4 tanggal)")
    print(f"  - Mask Tersedia             : {masks_available} chip")
    print(f"  - Mask Hilang/Tanpa Ref S2  : {masks_missing} chip")

    print("\n[C] 5 Chip dengan Proporsi Air Tertinggi:")
    print("-" * 75)
    # Filter chip yang memiliki data proporsi air valid
    flood_with_prop = [r for r in metadata_rows if r["proporsi_air"] != ""]
    if flood_with_prop:
        flood_with_prop.sort(key=lambda x: float(x["proporsi_air"]), reverse=True)
        top5 = flood_with_prop[:5]
        print(f"{'Chip ID':<8} | {'Tanggal':<10} | {'Proporsi Air':<14} | {'File S1':<30}")
        print("-" * 75)
        for r in top5:
            prop_pct = float(r["proporsi_air"]) * 100.0
            print(f"{r['chip_id']:<8} | {r['tanggal']:<10} | {prop_pct:>6.2f}% ({r['proporsi_air']}) | {r['file_s1']:<30}")
    else:
        print("  (Tidak ada data proporsi air; pastikan mask MNDWI telah diunduh)")

    print("-" * 75)
    print("✓ Seluruh proses konversi selesai dengan sukses.")
    print("=" * 70)


if __name__ == "__main__":
    main()

