#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import struct
from pathlib import Path

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None
    ImageOps = None

SECTOR_SIZE = 512
ROOT_ENTRY_COUNT = 512
ROOT_DIR_SECTORS = ROOT_ENTRY_COUNT * 32 // SECTOR_SIZE
FAT_COUNT = 2
RESERVED_SECTORS = 1
SECTORS_PER_CLUSTER = 1


def lfn_checksum(short_name: bytes) -> int:
    total = 0
    for byte in short_name:
        total = (((total & 1) << 7) + (total >> 1) + byte) & 0xFF
    return total


def make_short_name(value: str) -> bytes:
    raw = value.upper().replace(".", "")
    if len(raw) != 11 or not raw.isascii():
        raise SystemExit("--short-name must contain exactly 11 ASCII chars for 8.3 name")
    return raw.encode("ascii")


def write_utf16_chars(entry: bytearray, chars: list[int]) -> None:
    slots = [(1, 5), (14, 6), (28, 2)]
    index = 0
    terminated = False
    for offset, count in slots:
        for slot in range(count):
            if index < len(chars):
                value = chars[index]
                index += 1
            elif not terminated:
                value = 0x0000
                terminated = True
            else:
                value = 0xFFFF
            struct.pack_into("<H", entry, offset + slot * 2, value)


def make_lfn_entries(long_name: str, short_name: bytes) -> list[bytes]:
    chars = [ord(ch) for ch in long_name]
    chunks = [chars[i:i + 13] for i in range(0, len(chars), 13)]
    checksum = lfn_checksum(short_name)
    entries: list[bytes] = []

    for index in range(len(chunks), 0, -1):
        entry = bytearray(32)
        entry[0] = index | (0x40 if index == len(chunks) else 0x00)
        entry[11] = 0x0F
        entry[12] = 0x00
        entry[13] = checksum
        struct.pack_into("<H", entry, 26, 0)
        write_utf16_chars(entry, chunks[index - 1])
        entries.append(bytes(entry))

    return entries


def make_short_entry(short_name: bytes, first_cluster: int, file_size: int) -> bytes:
    entry = bytearray(32)
    entry[0:11] = short_name
    entry[11] = 0x20
    struct.pack_into("<H", entry, 20, (first_cluster >> 16) & 0xFFFF)
    struct.pack_into("<H", entry, 26, first_cluster & 0xFFFF)
    struct.pack_into("<I", entry, 28, file_size)
    return bytes(entry)


def compute_fat16_layout(total_sectors: int) -> tuple[int, int, int, int]:
    sectors_per_fat = 1
    while True:
        data_start = RESERVED_SECTORS + FAT_COUNT * sectors_per_fat + ROOT_DIR_SECTORS
        data_sectors = total_sectors - data_start
        cluster_count = data_sectors // SECTORS_PER_CLUSTER
        needed = math.ceil((cluster_count + 2) * 2 / SECTOR_SIZE)
        if needed == sectors_per_fat:
            return sectors_per_fat, data_start, data_sectors, cluster_count
        sectors_per_fat = needed


def set_fat16_entry(fat: bytearray, cluster: int, value: int) -> None:
    struct.pack_into("<H", fat, cluster * 2, value)


def create_fat16_image(zip_path: Path, output_path: Path, volume_label: str, short_name_text: str,
                       disk_size: int) -> None:
    if disk_size % SECTOR_SIZE != 0:
        raise SystemExit("disk size must be a multiple of 512 bytes")

    zip_data = zip_path.read_bytes()
    total_sectors = disk_size // SECTOR_SIZE
    sectors_per_fat, data_start, data_sectors, cluster_count = compute_fat16_layout(total_sectors)
    if cluster_count < 4085:
        raise SystemExit("disk is too small for FAT16")

    file_clusters = math.ceil(len(zip_data) / (SECTOR_SIZE * SECTORS_PER_CLUSTER))
    if file_clusters > cluster_count:
        raise SystemExit("zip file is too large for the generated disk image")

    image = bytearray(disk_size)
    boot = image[:SECTOR_SIZE]
    boot[0:3] = b"\xEB\x3C\x90"
    boot[3:11] = b"MSDOS5.0"
    struct.pack_into("<H", boot, 11, SECTOR_SIZE)
    boot[13] = SECTORS_PER_CLUSTER
    struct.pack_into("<H", boot, 14, RESERVED_SECTORS)
    boot[16] = FAT_COUNT
    struct.pack_into("<H", boot, 17, ROOT_ENTRY_COUNT)
    struct.pack_into("<H", boot, 19, total_sectors if total_sectors <= 0xFFFF else 0)
    boot[21] = 0xF8
    struct.pack_into("<H", boot, 22, sectors_per_fat)
    struct.pack_into("<H", boot, 24, 63)
    struct.pack_into("<H", boot, 26, 255)
    struct.pack_into("<I", boot, 28, 0)
    struct.pack_into("<I", boot, 32, total_sectors if total_sectors > 0xFFFF else 0)
    boot[36] = 0x80
    boot[38] = 0x29
    struct.pack_into("<I", boot, 39, 0x20260712)
    boot[43:54] = volume_label.upper().ljust(11)[:11].encode("ascii", errors="replace")
    boot[54:62] = b"FAT16   "
    boot[510:512] = b"\x55\xAA"

    fat = bytearray(sectors_per_fat * SECTOR_SIZE)
    set_fat16_entry(fat, 0, 0xFFF8)
    set_fat16_entry(fat, 1, 0xFFFF)
    first_cluster = 2
    for i in range(file_clusters):
        cluster = first_cluster + i
        next_value = 0xFFFF if i == file_clusters - 1 else cluster + 1
        set_fat16_entry(fat, cluster, next_value)

    fat1_start = RESERVED_SECTORS * SECTOR_SIZE
    fat_size = sectors_per_fat * SECTOR_SIZE
    image[fat1_start:fat1_start + fat_size] = fat
    fat2_start = fat1_start + fat_size
    image[fat2_start:fat2_start + fat_size] = fat

    root_start = (RESERVED_SECTORS + FAT_COUNT * sectors_per_fat) * SECTOR_SIZE
    root = bytearray(ROOT_DIR_SECTORS * SECTOR_SIZE)
    label = bytearray(32)
    label[0:11] = volume_label.upper().ljust(11)[:11].encode("ascii", errors="replace")
    label[11] = 0x08
    root[0:32] = label

    short_name = make_short_name(short_name_text)
    entries = make_lfn_entries(zip_path.name, short_name)
    entries.append(make_short_entry(short_name, first_cluster, len(zip_data)))
    offset = 32
    for entry in entries:
        root[offset:offset + 32] = entry
        offset += 32
    image[root_start:root_start + len(root)] = root

    data_offset = data_start * SECTOR_SIZE
    image[data_offset:data_offset + len(zip_data)] = zip_data

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image)
    print(f"disk image: {output_path} ({len(image):,} bytes)")
    print(f"file: {zip_path.name} ({len(zip_data):,} bytes)")
    print(f"fat16 clusters: {cluster_count}, sectors/fat: {sectors_per_fat}")


def rgb565_swapped_bytes(image: "Image.Image") -> bytes:
    pixels = image.convert("RGBA").tobytes()
    out = bytearray(image.width * image.height * 2)
    offset = 0
    for index in range(0, len(pixels), 4):
        r = pixels[index]
        g = pixels[index + 1]
        b = pixels[index + 2]
        a = pixels[index + 3]
        if a != 255:
            r = (r * a) // 255
            g = (g * a) // 255
            b = (b * a) // 255
        rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        out[offset] = rgb565 >> 8
        out[offset + 1] = rgb565 & 0xFF
        offset += 2
    return bytes(out)


def create_thumbnail(image_path: Path, output_path: Path, width: int, height: int) -> None:
    if Image is None or ImageOps is None:
        raise SystemExit("Pillow is required. Install with: python -m pip install pillow")

    source = Image.open(image_path).convert("RGBA")
    thumb = ImageOps.contain(source, (width, height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    canvas.alpha_composite(thumb, ((width - thumb.width) // 2, (height - thumb.height) // 2))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(rgb565_swapped_bytes(canvas))
    print(f"thumbnail: {output_path} ({output_path.stat().st_size:,} bytes)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create embedded USB installer disk and display thumbnail assets.")
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--disk-out", type=Path, default=Path("assets/host_package_fat.img"))
    parser.add_argument("--thumb-out", type=Path, default=Path("assets/usb_mode_image_rgb565.bin"))
    parser.add_argument("--volume-label", default="CPM")
    parser.add_argument("--short-name", required=True, help="11-char 8.3 alias without dot, for example CPMSTD12ZIP")
    parser.add_argument("--disk-size", type=int, default=4 * 1024 * 1024)
    parser.add_argument("--thumb-width", type=int, default=120)
    parser.add_argument("--thumb-height", type=int, default=64)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    zip_path = args.zip.resolve()
    image_path = args.image.resolve()
    if not zip_path.is_file():
        raise SystemExit(f"zip not found: {zip_path}")
    if not image_path.is_file():
        raise SystemExit(f"image not found: {image_path}")

    create_fat16_image(zip_path, args.disk_out, args.volume_label, args.short_name, args.disk_size)
    create_thumbnail(image_path, args.thumb_out, args.thumb_width, args.thumb_height)


if __name__ == "__main__":
    main()
