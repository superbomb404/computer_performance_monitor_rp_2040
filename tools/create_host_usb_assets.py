#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import struct
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
except ImportError:
    Image = None
    ImageDraw = None
    ImageFont = None
    ImageOps = None

SECTOR_SIZE = 512
RESERVED_SECTORS = 1
FAT_COUNT = 2
ROOT_ENTRY_COUNT = 16
ROOT_DIR_SECTORS = ROOT_ENTRY_COUNT * 32 // SECTOR_SIZE
SECTORS_PER_CLUSTER = 1
MIN_WINDOWS_SECTORS = 16


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
    if len(chunks) + 2 > ROOT_ENTRY_COUNT:
        raise SystemExit("file name is too long for the compact FAT12 root directory")

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
    struct.pack_into("<H", entry, 26, first_cluster & 0xFFFF)
    struct.pack_into("<I", entry, 28, file_size)
    return bytes(entry)


def set_fat12_entry(fat: bytearray, cluster: int, value: int) -> None:
    offset = cluster + cluster // 2
    value &= 0x0FFF
    if cluster & 1:
        fat[offset] = (fat[offset] & 0x0F) | ((value << 4) & 0xF0)
        fat[offset + 1] = (value >> 4) & 0xFF
    else:
        fat[offset] = value & 0xFF
        fat[offset + 1] = (fat[offset + 1] & 0xF0) | ((value >> 8) & 0x0F)


def fat12_sectors_for_clusters(cluster_count: int) -> int:
    fat_bytes = math.ceil((cluster_count + 2) * 3 / 2)
    return math.ceil(fat_bytes / SECTOR_SIZE)


def compute_fat12_layout(file_size: int, disk_size: int | None) -> tuple[int, int, int, int]:
    file_clusters = math.ceil(file_size / (SECTOR_SIZE * SECTORS_PER_CLUSTER))
    if file_clusters >= 4085:
        raise SystemExit("file is too large for FAT12 with 512-byte clusters")

    if disk_size is None:
        sectors_per_fat = fat12_sectors_for_clusters(file_clusters)
        while True:
            data_start = RESERVED_SECTORS + FAT_COUNT * sectors_per_fat + ROOT_DIR_SECTORS
            total_sectors = max(MIN_WINDOWS_SECTORS, data_start + file_clusters)
            cluster_count = (total_sectors - data_start) // SECTORS_PER_CLUSTER
            next_sectors_per_fat = fat12_sectors_for_clusters(cluster_count)
            if next_sectors_per_fat == sectors_per_fat:
                break
            sectors_per_fat = next_sectors_per_fat
    else:
        if disk_size % SECTOR_SIZE != 0:
            raise SystemExit("disk size must be a multiple of 512 bytes")
        total_sectors = disk_size // SECTOR_SIZE
        sectors_per_fat = 1
        while True:
            data_start = RESERVED_SECTORS + FAT_COUNT * sectors_per_fat + ROOT_DIR_SECTORS
            if total_sectors < data_start + file_clusters:
                raise SystemExit(
                    f"disk size is too small: need at least {(data_start + file_clusters) * SECTOR_SIZE} bytes"
                )
            cluster_count = (total_sectors - data_start) // SECTORS_PER_CLUSTER
            if cluster_count >= 4085:
                raise SystemExit("disk image would no longer be FAT12; reduce --disk-size")
            next_sectors_per_fat = fat12_sectors_for_clusters(cluster_count)
            if next_sectors_per_fat == sectors_per_fat:
                break
            sectors_per_fat = next_sectors_per_fat

    data_sectors = total_sectors - data_start
    cluster_count = data_sectors // SECTORS_PER_CLUSTER
    if cluster_count >= 4085:
        raise SystemExit("disk image would no longer be FAT12; reduce --disk-size")

    return sectors_per_fat, data_start, total_sectors, file_clusters


def create_fat12_image(zip_path: Path, output_path: Path, volume_label: str, short_name_text: str,
                       disk_size: int | None) -> None:
    zip_data = zip_path.read_bytes()
    sectors_per_fat, data_start, total_sectors, file_clusters = compute_fat12_layout(len(zip_data), disk_size)
    disk_bytes = total_sectors * SECTOR_SIZE
    image = bytearray(disk_bytes)

    boot = image[:SECTOR_SIZE]
    boot[0:3] = b"\xEB\x3C\x90"
    boot[3:11] = b"MSDOS5.0"
    struct.pack_into("<H", boot, 11, SECTOR_SIZE)
    boot[13] = SECTORS_PER_CLUSTER
    struct.pack_into("<H", boot, 14, RESERVED_SECTORS)
    boot[16] = FAT_COUNT
    struct.pack_into("<H", boot, 17, ROOT_ENTRY_COUNT)
    struct.pack_into("<H", boot, 19, total_sectors if total_sectors <= 0xFFFF else 0)
    boot[21] = 0xF0
    struct.pack_into("<H", boot, 22, sectors_per_fat)
    struct.pack_into("<H", boot, 24, 1)
    struct.pack_into("<H", boot, 26, 1)
    struct.pack_into("<I", boot, 28, 0)
    struct.pack_into("<I", boot, 32, total_sectors if total_sectors > 0xFFFF else 0)
    boot[36] = 0x00
    boot[38] = 0x29
    struct.pack_into("<I", boot, 39, 0x20260712)
    boot[43:54] = volume_label.upper().ljust(11)[:11].encode("ascii", errors="replace")
    boot[54:62] = b"FAT12   "
    boot[510:512] = b"\x55\xAA"
    image[:SECTOR_SIZE] = boot

    fat = bytearray(sectors_per_fat * SECTOR_SIZE)
    set_fat12_entry(fat, 0, 0xFF0)
    set_fat12_entry(fat, 1, 0xFFF)
    first_cluster = 2
    for i in range(file_clusters):
        cluster = first_cluster + i
        next_value = 0xFFF if i == file_clusters - 1 else cluster + 1
        set_fat12_entry(fat, cluster, next_value)

    for fat_index in range(FAT_COUNT):
        fat_start = (RESERVED_SECTORS + fat_index * sectors_per_fat) * SECTOR_SIZE
        image[fat_start:fat_start + len(fat)] = fat

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
    print(f"filesystem: FAT12, sector=512, cluster=512, FATs={FAT_COUNT}")
    print(f"file: {zip_path.name} ({len(zip_data):,} bytes)")
    print(f"data start sector: {data_start}, sectors/FAT: {sectors_per_fat}, file clusters: {file_clusters}")


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


def load_font(size: int) -> "ImageFont.FreeTypeFont":
    if ImageFont is None:
        raise SystemExit("Pillow is required. Install with: python -m pip install pillow")

    font_paths = [
        Path("C:/Windows/Fonts/msyhbd.ttc"),
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/simsun.ttc"),
    ]
    for font_path in font_paths:
        if font_path.exists():
            return ImageFont.truetype(str(font_path), size)
    raise SystemExit("no Chinese-capable Windows font was found")


def draw_centered_text(draw: "ImageDraw.ImageDraw", text: str, font: "ImageFont.FreeTypeFont",
                       y: int, fill: tuple[int, int, int]) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    draw.text(((320 - width) // 2, y), text, font=font, fill=fill)


def create_usb_mode_screen(image_path: Path, output_path: Path, width: int, height: int) -> None:
    if Image is None or ImageDraw is None or ImageOps is None:
        raise SystemExit("Pillow is required. Install with: python -m pip install pillow")

    logo = Image.open(image_path).convert("RGBA")
    canvas = Image.new("RGBA", (width, height), (16, 16, 16, 255))
    logo_box = (112, 66)
    logo = ImageOps.contain(logo, logo_box, Image.Resampling.LANCZOS)
    logo_x = (width - logo.width) // 2
    logo_y = 18
    canvas.alpha_composite(logo, (logo_x, logo_y))

    draw = ImageDraw.Draw(canvas)
    font = load_font(20)
    line1 = "\u5f53\u524d\u4e3aU\u76d8\u6a21\u5f0f"
    line2 = "\u8bf7\u6253\u5f00\u7535\u8111\u5b89\u88c5\u4e0a\u4f4d\u673a\u7a0b\u5e8f"
    text_y = logo_y + logo.height + 13
    draw_centered_text(draw, line1, font, text_y, (255, 255, 255))
    draw_centered_text(draw, line2, font, text_y + 27, (255, 255, 255))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(rgb565_swapped_bytes(canvas))
    print(f"usb mode screen: {output_path} ({output_path.stat().st_size:,} bytes)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create embedded FAT12 USB installer disk and display image assets.")
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--disk-out", type=Path, default=Path("assets/host_package_fat.img"))
    parser.add_argument("--thumb-out", type=Path, default=Path("assets/usb_mode_image_rgb565.bin"))
    parser.add_argument("--volume-label", default="CPM")
    parser.add_argument("--short-name", required=True, help="11-char 8.3 alias without dot, for example CPMSTD12ZIP")
    parser.add_argument("--disk-size", type=int, default=0, help="optional disk image size in bytes; 0 means minimum")
    parser.add_argument("--thumb-width", type=int, default=320)
    parser.add_argument("--thumb-height", type=int, default=170)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    zip_path = args.zip.resolve()
    image_path = args.image.resolve()
    if not zip_path.is_file():
        raise SystemExit(f"zip not found: {zip_path}")
    if not image_path.is_file():
        raise SystemExit(f"image not found: {image_path}")

    create_fat12_image(
        zip_path,
        args.disk_out,
        args.volume_label,
        args.short_name,
        None if args.disk_size == 0 else args.disk_size,
    )
    create_usb_mode_screen(image_path, args.thumb_out, args.thumb_width, args.thumb_height)


if __name__ == "__main__":
    main()
