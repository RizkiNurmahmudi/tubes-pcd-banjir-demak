#!/usr/bin/env python3
"""
=============================================================================
Tubes Pengolahan Citra Digital (PCD) Kelompok 6
Dataset Banjir Demak (Kecamatan Karanganyar & Gajah, Kab. Demak)
SCRIPT 1: export_dataset_gee.py

Deskripsi:
Script ini mengotomatisasi export dataset citra Sentinel-1 (VV, dB) dan mask
referensi MNDWI dari Sentinel-2 menggunakan Google Earth Engine Python API.
Hasil export disimpan langsung ke Google Drive di folder 'dataset_demak_tubes'.

Karakteristik Grid & Dataset:
- ROI: [110.68, -6.90, 110.82, -6.79] (Kec. Karanganyar + Gajah, Kab. Demak)
- Grid: 6 kolom x 5 baris = 30 chip
- Resolusi chip: 256x256 piksel pada 10 m (2,56 km x 2,56 km)
- Jangkar: Sudut barat laut (lon: 110.68, lat: -6.79)
- Sentinel-1 (COPERNICUS/S1_GRD, IW, VV, dB float):
  1. Pra-banjir: Komposit median Januari 2024, descending
  2. 15 Maret 2024, descending (orbit 76)
  3. 19 Maret 2024, ascending (orbit 127)
  4. 27 Maret 2024, descending (orbit 76)
  5. 31 Maret 2024, ascending (orbit 127)
  Total: 30 chip x 5 tanggal = 150 citra Sentinel-1
- Mask referensi MNDWI dari Sentinel-2 (COPERNICUS/S2_SR_HARMONIZED):
  Citra S2 terdekat dalam rentang ±10 hari (tutupan awan <20%, cloud mask SCL).
  MNDWI = (B3 - B11) / (B3 + B11), threshold MNDWI > 0.
- Manifest: export_manifest.csv disimpan di PROJECT_DIR.
=============================================================================
"""

import os
import sys
import math
import csv
from datetime import datetime, timedelta
from pathlib import Path

# =============================================================================
# KONFIGURASI PROYEK & DIREKTORI
# =============================================================================
# PROJECT_DIR: Direktori utama proyek. Semua output lokal (manifest) disimpan di sini.
PROJECT_DIR = Path(__file__).resolve().parent

# Opsional: Jika akun Google Cloud Anda memerlukan Google Cloud Project ID spesifik
# untuk Earth Engine, isi string di bawah ini (misal: 'my-gee-project').
# Jika dibiarkan None, ee.Initialize() akan menggunakan konfigurasi default Anda.
GEE_PROJECT = None

# Nama folder target di Google Drive
DRIVE_FOLDER = "dataset_demak_tubes"

# ROI: [min_lon, min_lat, max_lon, max_lat]
ROI_BOUNDS = [110.68, -6.90, 110.82, -6.79]
WEST = ROI_BOUNDS[0]
SOUTH = ROI_BOUNDS[1]
EAST = ROI_BOUNDS[2]
NORTH = ROI_BOUNDS[3]

# Grid Chip: 6 kolom x 5 baris
GRID_COLS = 6
GRID_ROWS = 5
CHIP_PIXELS = 256
PIXEL_SCALE = 10  # 10 meter per piksel
CHIP_SIZE_M = CHIP_PIXELS * PIXEL_SCALE  # 2560 meter (2.56 km)


def init_earth_engine(project_id: str = None):
    """
    Melakukan inisialisasi dan autentikasi Earth Engine jika diperlukan.
    """
    import ee

    print("-" * 70)
    print("Inisialisasi Google Earth Engine...")
    try:
        if project_id:
            ee.Initialize(project=project_id)
        else:
            ee.Initialize()
        print("✓ Berhasil terhubung ke Google Earth Engine.")
    except Exception as err:
        print(f"! Inisialisasi awal memerlukan autentikasi: {err}")
        print("! Menjalankan ee.Authenticate()... Silakan ikuti instruksi di layar.")
        ee.Authenticate()
        if project_id:
            ee.Initialize(project=project_id)
        else:
            ee.Initialize()
        print("✓ Berhasil terautentikasi dan terhubung ke Google Earth Engine.")
    print("-" * 70)


def generate_chip_grid():
    """
    Membuat 30 chip (6 kolom x 5 baris) dengan ukuran 2560m x 2560m (256x256 piksel @ 10m).
    Jangkar diletakkan di sudut barat laut ROI (WEST, NORTH) = (110.68, -6.79).
    Koordinat chip bergerak ke arah Timur (kolom c00..c05) dan Selatan (baris r00..r04).
    """
    import ee

    # Konversi meter ke derajat berdasarkan WGS84 pada latitude Demak (~ -6.79°)
    lat_ref_rad = math.radians(NORTH)

    # Jarak per derajat latitude (meridian arc)
    m_per_deg_lat = (
        111132.92
        - 559.82 * math.cos(2 * lat_ref_rad)
        + 1.175 * math.cos(4 * lat_ref_rad)
    )

    # Jarak per derajat longitude (parallel arc)
    a = 6378137.0  # WGS84 semi-major axis
    e2 = 0.00669437999014  # WGS84 eccentricity squared
    m_per_deg_lon = (
        (math.pi / 180.0)
        * a
        * math.cos(lat_ref_rad)
        / math.sqrt(1.0 - e2 * (math.sin(lat_ref_rad) ** 2))
    )

    d_lat = CHIP_SIZE_M / m_per_deg_lat  # ~ 0.02315°
    d_lon = CHIP_SIZE_M / m_per_deg_lon  # ~ 0.02316°

    chips = []
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            chip_id = f"r{r:02d}_c{c:02d}"
            c_min_lon = WEST + c * d_lon
            c_max_lon = WEST + (c + 1) * d_lon
            c_max_lat = NORTH - r * d_lat
            c_min_lat = NORTH - (r + 1) * d_lat

            geom = ee.Geometry.Rectangle(
                [c_min_lon, c_min_lat, c_max_lon, c_max_lat],
                proj="EPSG:4326",
                geodesic=False,
            )

            chips.append({
                "chip_id": chip_id,
                "row": r,
                "col": c,
                "min_lon": c_min_lon,
                "min_lat": c_min_lat,
                "max_lon": c_max_lon,
                "max_lat": c_max_lat,
                "geometry": geom,
            })

    return chips


def build_s1_collection(roi_geom, start_date, end_date, pass_direction, orbit_num=None):
    """
    Membuat koleksi Sentinel-1 GRD IW polarisasi VV yang memotong ROI.
    """
    import ee

    col = (
        ee.ImageCollection("COPERNICUS/S1_GRD")
        .filterBounds(roi_geom)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.eq("orbitProperties_pass", pass_direction))
    )

    if orbit_num is not None:
        col_orbit = col.filter(ee.Filter.eq("relativeOrbitNumber_start", orbit_num))
        # Jika filter orbit memiliki citra, gunakan filter tersebut
        col = ee.ImageCollection(
            ee.Algorithms.If(col_orbit.size().gt(0), col_orbit, col)
        )

    return col


def get_s2_reference_mask(roi_geom, target_date_str):
    """
    Mencari citra Sentinel-2 L2A (S2_SR_HARMONIZED) terdekat dalam rentang ±10 hari
    dari target_date dengan tutupan awan <20%.
    Menggunakan band SCL untuk cloud masking.
    Menghitung MNDWI = (B3 - B11) / (B3 + B11), mask = MNDWI > 0.
    Jika tidak ada citra yang memenuhi syarat, mengembalikan (None, 'tanpa referensi').
    """
    import ee

    target_dt = datetime.strptime(target_date_str, "%Y-%m-%d")
    start_dt = target_dt - timedelta(days=10)
    end_dt = target_dt + timedelta(days=11)  # inklusif 10 hari ke depan

    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")

    s2_col = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(roi_geom)
        .filterDate(start_str, end_str)
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
    )

    # Urutkan berdasarkan jarak waktu terkecil ke tanggal target
    target_millis = ee.Date(target_date_str).millis()

    def add_time_diff(img):
        diff = ee.Number(img.get("system:time_start")).subtract(target_millis).abs()
        return img.set("time_diff_to_target", diff)

    s2_with_diff = s2_col.map(add_time_diff).sort("time_diff_to_target")

    count = s2_with_diff.size().getInfo()
    if count == 0:
        return None, "tanpa referensi"

    # Ambil citra terdekat
    best_img = ee.Image(s2_with_diff.first())
    best_time_millis = best_img.get("system:time_start").getInfo()
    best_date_str = datetime.utcfromtimestamp(best_time_millis / 1000.0).strftime("%Y-%m-%d")

    # Ambil semua granule pada tanggal tersebut jika ROI terbagi di batas granule
    best_day_start = best_date_str
    best_day_end = (datetime.strptime(best_date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    day_col = s2_col.filterDate(best_day_start, best_day_end)

    # Fungsi mask awan menggunakan Scene Classification Layer (SCL)
    def mask_s2_scl(img):
        scl = img.select("SCL")
        # Piksel awan & bayangan: 3=cloud shadow, 8=cloud med, 9=cloud high, 10=cirrus, 1=defective
        valid_mask = (
            scl.neq(3)
            .And(scl.neq(8))
            .And(scl.neq(9))
            .And(scl.neq(10))
            .And(scl.neq(1))
        )
        return img.updateMask(valid_mask)

    masked_col = day_col.map(mask_s2_scl)
    s2_mosaic = masked_col.mosaic()

    # B3 = Green, B11 = SWIR1
    # MNDWI = (Green - SWIR1) / (Green + SWIR1)
    mndwi = s2_mosaic.normalizedDifference(["B3", "B11"]).rename("MNDWI")

    # Mask air: MNDWI > 0 (1 = air, 0 = non-air/awan tertutup)
    water_mask = mndwi.gt(0).rename("water_mask").toByte().unmask(0)

    return water_mask, best_date_str


def main():
    import ee

    print("=" * 70)
    print("TUBES PCD KELOMPOK 6 - EXPORT DATASET BANJIR DEMAK KE GOOGLE DRIVE")
    print(f"Direktori Proyek (PROJECT_DIR): {PROJECT_DIR}")
    print(f"Target Folder Drive           : {DRIVE_FOLDER}")
    print("=" * 70)

    # 1. Inisialisasi GEE
    init_earth_engine(GEE_PROJECT)

    # 2. Geometri ROI Keseluruhan
    roi_geom = ee.Geometry.Rectangle(ROI_BOUNDS, proj="EPSG:4326", geodesic=False)

    # 3. Buat Grid Chip (30 chip)
    print("\n[1/4] Membuat grid 6 kolom x 5 baris (30 chip)...")
    chips = generate_chip_grid()
    print(f"✓ Berhasil membuat {len(chips)} geometri chip (resolusi 256x256 piksel @ 10m).")
    print(f"  Barat-Laut: ({chips[0]['min_lon']:.4f}, {chips[0]['max_lat']:.4f})")
    print(f"  Tenggara  : ({chips[-1]['max_lon']:.4f}, {chips[-1]['min_lat']:.4f})")

    # 4. Konfigurasi Tanggal Citra Sentinel-1
    s1_configs = [
        {
            "tag": "preflood",
            "date_file": "20240101",
            "date_display": "Januari 2024 (Median Komposit)",
            "start": "2024-01-01",
            "end": "2024-02-01",
            "pass": "DESCENDING",
            "orbit": None,
            "is_median": True,
            "is_flood": False,
        },
        {
            "tag": "flood_20240315",
            "date_file": "20240315",
            "date_display": "15 Maret 2024",
            "start": "2024-03-15",
            "end": "2024-03-16",
            "pass": "DESCENDING",
            "orbit": 76,
            "is_median": False,
            "is_flood": True,
            "target_date_str": "2024-03-15",
        },
        {
            "tag": "flood_20240319",
            "date_file": "20240319",
            "date_display": "19 Maret 2024",
            "start": "2024-03-19",
            "end": "2024-03-20",
            "pass": "ASCENDING",
            "orbit": 127,
            "is_median": False,
            "is_flood": True,
            "target_date_str": "2024-03-19",
        },
        {
            "tag": "flood_20240327",
            "date_file": "20240327",
            "date_display": "27 Maret 2024",
            "start": "2024-03-27",
            "end": "2024-03-28",
            "pass": "DESCENDING",
            "orbit": 76,
            "is_median": False,
            "is_flood": True,
            "target_date_str": "2024-03-27",
        },
        {
            "tag": "flood_20240331",
            "date_file": "20240331",
            "date_display": "31 Maret 2024",
            "start": "2024-03-31",
            "end": "2024-04-01",
            "pass": "ASCENDING",
            "orbit": 127,
            "is_median": False,
            "is_flood": True,
            "target_date_str": "2024-03-31",
        },
    ]

    # Siapkan Citra Sentinel-1 (VV, dB apa adanya)
    print("\n[2/4] Menyiapkan citra Sentinel-1 (VV, IW, dB)...")
    s1_images = {}
    for cfg in s1_configs:
        col = build_s1_collection(
            roi_geom=roi_geom,
            start_date=cfg["start"],
            end_date=cfg["end"],
            pass_direction=cfg["pass"],
            orbit_num=cfg["orbit"],
        )
        if cfg["is_median"]:
            img = col.select("VV").median()
        else:
            img = col.select("VV").mosaic()

        s1_images[cfg["date_file"]] = {
            "image": img,
            "config": cfg,
        }
        print(f"  ✓ S1 {cfg['date_display']} ({cfg['pass']}, orbit {cfg['orbit'] or 'all'}) siap.")

    # 5. Cari Citra Mask MNDWI Sentinel-2 untuk Tiap Tanggal Banjir
    print("\n[3/4] Mencari mask referensi Sentinel-2 MNDWI (±10 hari, awan <20%)...")
    s2_masks = {}
    for cfg in s1_configs:
        if not cfg["is_flood"]:
            continue
        t_str = cfg["target_date_str"]
        print(f"  Mengecek referensi S2 untuk tanggal banjir {t_str}...", end=" ")
        mask_img, ref_date = get_s2_reference_mask(roi_geom, t_str)
        if mask_img is not None:
            s2_masks[cfg["date_file"]] = {
                "mask": mask_img,
                "ref_date": ref_date,
            }
            print(f"DITEMUKAN (Citra S2 tanggal {ref_date})")
        else:
            s2_masks[cfg["date_file"]] = {
                "mask": None,
                "ref_date": "tanpa referensi",
            }
            print("TANPA REFERENSI (tidak ada citra awan <20% dalam rentang ±10 hari; lanjut tanpa mask)")

    # 6. Jalankan ee.batch.Export.image.toDrive
    print("\n[4/4] Mendaftarkan tasks export ke Google Drive...")
    print(f"  Folder Drive : '{DRIVE_FOLDER}'")
    print(f"  Resolusi     : {PIXEL_SCALE} m (256x256 piksel per chip)")
    print(f"  Format       : GeoTIFF float (S1 VV dB) dan Byte 0/1 (MNDWI mask)")

    export_records = []
    task_count_s1 = 0
    task_count_mask = 0

    for chip in chips:
        c_id = chip["chip_id"]
        c_geom = chip["geometry"]

        # Export Sentinel-1 untuk semua 5 tanggal
        for cfg in s1_configs:
            date_file = cfg["date_file"]
            s1_info = s1_images[date_file]
            file_name = f"chip_{c_id}_{date_file}_VV"

            task = ee.batch.Export.image.toDrive(
                image=s1_info["image"],
                description=file_name,
                folder=DRIVE_FOLDER,
                fileNamePrefix=file_name,
                region=c_geom,
                scale=PIXEL_SCALE,
                fileFormat="GeoTIFF",
                maxPixels=1e9,
            )
            task.start()
            task_count_s1 += 1

            export_records.append({
                "task_id": task.id or f"task_{task_count_s1}",
                "chip_id": c_id,
                "row": chip["row"],
                "col": chip["col"],
                "tanggal": date_file,
                "jenis": "s1_preflood" if not cfg["is_flood"] else "s1_flood",
                "file_name": f"{file_name}.tif",
                "status": task.status().get("state", "READY"),
                "s2_reference_date": "-",
                "min_lon": f"{chip['min_lon']:.6f}",
                "min_lat": f"{chip['min_lat']:.6f}",
                "max_lon": f"{chip['max_lon']:.6f}",
                "max_lat": f"{chip['max_lat']:.6f}",
            })

        # Export Mask MNDWI untuk tanggal banjir jika referensi tersedia
        for cfg in s1_configs:
            if not cfg["is_flood"]:
                continue
            date_file = cfg["date_file"]
            mask_info = s2_masks.get(date_file)

            if mask_info and mask_info["mask"] is not None:
                mask_file_name = f"chip_{c_id}_{date_file}_mask"
                task_m = ee.batch.Export.image.toDrive(
                    image=mask_info["mask"],
                    description=mask_file_name,
                    folder=DRIVE_FOLDER,
                    fileNamePrefix=mask_file_name,
                    region=c_geom,
                    scale=PIXEL_SCALE,
                    fileFormat="GeoTIFF",
                    maxPixels=1e9,
                )
                task_m.start()
                task_count_mask += 1

                export_records.append({
                    "task_id": task_m.id or f"task_m_{task_count_mask}",
                    "chip_id": c_id,
                    "row": chip["row"],
                    "col": chip["col"],
                    "tanggal": date_file,
                    "jenis": "mask_mndwi",
                    "file_name": f"{mask_file_name}.tif",
                    "status": task_m.status().get("state", "READY"),
                    "s2_reference_date": mask_info["ref_date"],
                    "min_lon": f"{chip['min_lon']:.6f}",
                    "min_lat": f"{chip['min_lat']:.6f}",
                    "max_lon": f"{chip['max_lon']:.6f}",
                    "max_lat": f"{chip['max_lat']:.6f}",
                })

    # Simpan export_manifest.csv
    manifest_path = PROJECT_DIR / "export_manifest.csv"
    with open(manifest_path, mode="w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "task_id",
            "chip_id",
            "row",
            "col",
            "tanggal",
            "jenis",
            "file_name",
            "status",
            "s2_reference_date",
            "min_lon",
            "min_lat",
            "max_lon",
            "max_lat",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(export_records)

    # Cetak Rekapitulasi Tasks
    print("\n" + "=" * 70)
    print("REKAPITULASI TUGAS EXPORT GOOGLE EARTH ENGINE")
    print("=" * 70)
    print(f"Total chip lokasi               : {len(chips)} chip (6 kolom x 5 baris)")
    print(f"Total task citra Sentinel-1     : {task_count_s1} (30 chip x 5 tanggal)")
    print(f"Total task mask Sentinel-2 MNDWI: {task_count_mask} (chip banjir ber-referensi)")
    print(f"Total keseluruhan tasks export  : {len(export_records)} tasks")
    print(f"Manifest tersimpan di           : {manifest_path}")
    print("-" * 70)
    print("Contoh 10 Task Pertama yang Dibuat:")
    print(f"{'Task ID':<25} | {'Chip':<8} | {'Jenis':<12} | {'File Name':<32} | {'Status'}")
    print("-" * 95)
    for rec in export_records[:10]:
        print(f"{str(rec['task_id']):<25} | {rec['chip_id']:<8} | {rec['jenis']:<12} | {rec['file_name']:<32} | {rec['status']}")
    if len(export_records) > 10:
        print(f"... dan {len(export_records) - 10} task lainnya (lihat export_manifest.csv).")
    print("-" * 70)
    print("CATATAN PENTING:")
    print("1. Tasks sekarang sedang berjalan di server Google Earth Engine.")
    print("2. Anda dapat memantau progres export di browser melalui:")
    print("   https://code.earthengine.google.com/tasks")
    print(f"3. File GeoTIFF akan masuk ke folder Google Drive Anda: '{DRIVE_FOLDER}'.")
    print("4. Setelah semua export selesai, unduh folder tersebut ke folder lokal 'dataset/'")
    print("   lalu jalankan script kedua: python convert_dataset.py")
    print("=" * 70)


if __name__ == "__main__":
    main()

