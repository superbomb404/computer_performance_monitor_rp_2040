#!/usr/bin/env python3
"""从逐帧图片生成启动动画 RGB565 数据，并可选编译 UF2 固件。"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - 面向用户的依赖检查
    Image = None


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
FALLBACK_DRIVE_LETTERS = ("U", "T", "S", "R", "Q")
COMMON_EMBEDDED_OBJECTS = ("host_package_disk.S.obj", "usb_mode_image.S.obj")


@dataclass(frozen=True)
class AnimationProfile:
    key: str
    display_name: str
    header_name: str
    asm_name: str
    output_name: str
    object_name: str
    width_macro: str
    height_macro: str
    frame_count_macro: str
    repeat_count_macro: str
    frame_delay_macro: str
    final_hold_macro: str | None
    frame_size_macro: str
    total_size_macro: str
    default_frame_dirs: tuple[str, ...]


ANIMATION_PROFILES = (
    AnimationProfile(
        key="startup",
        display_name="ROG/通用开机动画",
        header_name="startup_animation.h",
        asm_name="startup_animation.S.in",
        output_name="assets/startup_frames_rgb565.bin",
        object_name="startup_animation.S.obj",
        width_macro="STARTUP_FRAME_WIDTH",
        height_macro="STARTUP_FRAME_HEIGHT",
        frame_count_macro="STARTUP_FRAME_COUNT",
        repeat_count_macro="STARTUP_REPEAT_COUNT",
        frame_delay_macro="STARTUP_FRAME_DELAY_MS",
        final_hold_macro="STARTUP_FINAL_FRAME_HOLD_MS",
        frame_size_macro="STARTUP_FRAME_SIZE_BYTES",
        total_size_macro="STARTUP_ANIMATION_SIZE_BYTES",
        default_frame_dirs=("ROG动画 逐帧", "ROG動畫 逐幀", "ROG"),
    ),
    AnimationProfile(
        key="doro",
        display_name="Doro 开机动画",
        header_name="doro_animation.h",
        asm_name="doro_animation.S.in",
        output_name="assets/doro_frames_rgb565.bin",
        object_name="doro_animation.S.obj",
        width_macro="DORO_FRAME_WIDTH",
        height_macro="DORO_FRAME_HEIGHT",
        frame_count_macro="DORO_FRAME_COUNT",
        repeat_count_macro="DORO_FRAME_REPEAT_COUNT",
        frame_delay_macro="DORO_FRAME_DELAY_MS",
        final_hold_macro=None,
        frame_size_macro="DORO_FRAME_SIZE_BYTES",
        total_size_macro="DORO_ANIMATION_SIZE_BYTES",
        default_frame_dirs=("doro逐帧", "Doro逐帧", "DORO逐帧", "doro"),
    ),
)


def natural_key(path: Path) -> list[object]:
    parts = re.split(r"(\d+)", path.stem)
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def read_macro_int(header_path: Path, name: str, default: int | None = None) -> int | None:
    if not header_path.exists():
        return default
    text = header_path.read_text(encoding="utf-8")
    match = re.search(rf"^#define\s+{re.escape(name)}\s+(\d+)u?\b", text, re.MULTILINE)
    return int(match.group(1)) if match else default


def detect_animation_profile(repo_root: Path) -> AnimationProfile:
    cmake_path = repo_root / "CMakeLists.txt"
    cmake_text = cmake_path.read_text(encoding="utf-8") if cmake_path.exists() else ""
    matches: list[AnimationProfile] = []
    for profile in ANIMATION_PROFILES:
        if (repo_root / profile.header_name).exists() and profile.asm_name in cmake_text:
            matches.append(profile)

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = "、".join(profile.display_name for profile in matches)
        raise SystemExit(f"检测到多个动画配置：{names}。请检查当前分支的 CMakeLists.txt。")

    print("\n==== 工程检查失败 ====")
    print("未检测到当前程序支持的开机动画资源布局。")
    print("请先切换到 Doro 或 ROG-Logo 分支，再运行此脚本。")
    raise SystemExit(1)


def ensure_animation_project(repo_root: Path, profile: AnimationProfile) -> None:
    required_files = [
        repo_root / profile.header_name,
        repo_root / profile.asm_name,
        repo_root / "host_package_disk.S.in",
        repo_root / "usb_mode_image.S.in",
        repo_root / "CMakeLists.txt",
    ]
    missing = [path for path in required_files if not path.exists()]
    if missing:
        print("\n==== 工程检查失败 ====")
        for path in missing:
            print(f"缺少文件：{path}")
        raise SystemExit("当前分支缺少开机动画或 U 盘模式需要的资源文件。")

    cmake_text = (repo_root / "CMakeLists.txt").read_text(encoding="utf-8")
    for token in (profile.asm_name.replace(".in", ""), "host_package_disk.S", "usb_mode_image.S"):
        if token not in cmake_text:
            raise SystemExit(f"CMakeLists.txt 未引用 {token}，请先切换到支持当前资源布局的固件分支。")


def find_frames(folder: Path) -> list[Path]:
    frames = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    if not frames:
        raise SystemExit(f"未在目录中找到支持的图片文件：{folder}")

    numeric_frames = [p for p in frames if p.stem.isdigit()]
    if len(numeric_frames) == len(frames):
        frames.sort(key=lambda p: int(p.stem))
        print("排序方式：检测到纯数字帧名，按数字升序排序。")
    else:
        frames.sort(key=natural_key)
        print("排序方式：检测到非纯数字帧名，按自然排序规则排序。")
    return frames


def first_existing_dir(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.is_dir():
            return path
    return None


def default_frame_dir(workspace_root: Path, profile: AnimationProfile) -> Path | None:
    return first_existing_dir([workspace_root / name for name in profile.default_frame_dirs])


def prompt_path(message: str, default: Path | None = None) -> Path:
    suffix = f" [{default}]" if default else ""
    value = input(f"{message}{suffix}: ").strip().strip('"')
    path = Path(value) if value else default
    if path is None:
        raise SystemExit("必须提供逐帧图片文件夹。")
    path = path.expanduser().resolve()
    if not path.is_dir():
        raise SystemExit(f"逐帧图片文件夹不存在：{path}")
    return path


def prompt_float(message: str, default: float | None = None) -> float:
    suffix = f" [{default:g}]" if default is not None else ""
    while True:
        value = input(f"{message}{suffix}: ").strip()
        if not value and default is not None:
            return default
        try:
            parsed = float(value)
        except ValueError:
            print("请输入数字。")
            continue
        if parsed <= 0:
            print("数值必须大于 0。")
            continue
        return parsed


def prompt_int(message: str, default: int | None = None, min_value: int = 0) -> int:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        value = input(f"{message}{suffix}: ").strip()
        if not value and default is not None:
            return default
        try:
            parsed = int(value)
        except ValueError:
            print("请输入整数。")
            continue
        if parsed < min_value:
            print(f"数值必须大于或等于 {min_value}。")
            continue
        return parsed


def prompt_yes_no(message: str, default: bool = False) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    while True:
        value = input(f"{message}{suffix}: ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes", "是"}:
            return True
        if value in {"n", "no", "否"}:
            return False
        print("请输入 y 或 n。")


def rgb565_bytes(image_path: Path, expected_size: tuple[int, int]) -> bytes:
    assert Image is not None
    image = Image.open(image_path).convert("RGBA")
    if image.size != expected_size:
        raise SystemExit(f"{image_path.name} 尺寸不一致：期望 {expected_size}，实际 {image.size}")

    out = bytearray(expected_size[0] * expected_size[1] * 2)
    offset = 0
    pixels = image.tobytes()
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


def generate_rgb565_blob(frames: list[Path], output_path: Path) -> tuple[int, int, int]:
    if Image is None:
        raise SystemExit("缺少 Pillow。请先安装：python -m pip install pillow")

    with Image.open(frames[0]) as first:
        width, height = first.size

    frame_size = width * height * 2
    total_size = frame_size * len(frames)

    print("\n==== 动画资源分析 ====")
    print(f"逐帧目录：{frames[0].parent}")
    print(f"首帧文件：{frames[0].name}")
    print(f"末帧文件：{frames[-1].name}")
    print(f"检测到帧数：{len(frames)}")
    print(f"单帧尺寸：{width} x {height}")
    print(f"RGB565 单帧大小：{frame_size:,} bytes")
    print(f"预计输出文件大小：{total_size:,} bytes ({total_size / 1024 / 1024:.2f} MiB)")
    print(f"输出文件：{output_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as out:
        for index, frame in enumerate(frames, 1):
            out.write(rgb565_bytes(frame, (width, height)))
            current_size = index * frame_size
            print(f"转换帧 {index:03d}/{len(frames):03d}：{frame.name}，累计 {current_size:,} bytes")

    actual_size = output_path.stat().st_size
    if actual_size != total_size:
        raise SystemExit(f"生成文件大小不匹配：期望 {total_size}，实际 {actual_size}")
    print(f"生成完成：{output_path}")
    return width, height, total_size


def replace_define(text: str, name: str, value: int) -> str:
    pattern = re.compile(rf"^#define\s+{re.escape(name)}\s+.+$", re.MULTILINE)
    replacement = f"#define {name} {value}u"
    if not pattern.search(text):
        raise SystemExit(f"未在动画头文件中找到宏：{name}")
    return pattern.sub(replacement, text)


def update_header(
    header_path: Path,
    profile: AnimationProfile,
    *,
    width: int,
    height: int,
    frame_count: int,
    repeat_count: int,
    frame_delay_ms: int,
    final_hold_ms: int,
    frame_size: int,
    total_size: int,
) -> None:
    text = header_path.read_text(encoding="utf-8")
    replacements: list[tuple[str | None, int]] = [
        (profile.width_macro, width),
        (profile.height_macro, height),
        (profile.frame_count_macro, frame_count),
        (profile.repeat_count_macro, repeat_count),
        (profile.frame_delay_macro, frame_delay_ms),
        (profile.final_hold_macro, final_hold_ms),
        (profile.frame_size_macro, frame_size),
        (profile.total_size_macro, total_size),
    ]
    print("\n==== 更新固件参数 ====")
    for name, value in replacements:
        if name is None:
            continue
        print(f"{name} = {value}")
        text = replace_define(text, name, value)
    header_path.write_text(text, encoding="utf-8", newline="\n")
    print(f"已更新：{header_path}")


def print_flash_estimate(repo_root: Path, animation_output: Path, animation_size: int) -> None:
    asset_paths = [
        animation_output,
        repo_root / "assets/host_package_fat.img",
        repo_root / "assets/usb_mode_image_rgb565.bin",
    ]
    print("\n==== Flash 资源估算 ====")
    total_assets = 0
    for path in asset_paths:
        size = path.stat().st_size if path.exists() else animation_size if path == animation_output else 0
        total_assets += size
        print(f"{path.name}: {size:,} bytes ({size / 1024 / 1024:.2f} MiB)")
    print(f"嵌入资源合计约：{total_assets:,} bytes ({total_assets / 1024 / 1024:.2f} MiB)")
    if total_assets > 16 * 1024 * 1024:
        print("警告：仅资源文件已超过 16 MiB，固件肯定无法放入当前板载 flash。")


def run(command: list[str], *, cwd: Path) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def path_has_non_ascii(path: Path) -> bool:
    try:
        str(path).encode("ascii")
        return False
    except UnicodeEncodeError:
        return True


def current_subst_mappings() -> dict[str, str]:
    if os.name != "nt":
        return {}
    result = subprocess.run(["cmd", "/c", "subst"], text=True, capture_output=True, check=False)
    mappings: dict[str, str] = {}
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if "=>" not in line:
            continue
        left, right = line.split("=>", 1)
        drive = left.strip()[:1].upper()
        if re.fullmatch(r"[A-Z]", drive):
            mappings[drive] = right.strip()
    return mappings


def subst_workspace(workspace_root: Path) -> tuple[Path, str | None]:
    if os.name != "nt" or not path_has_non_ascii(workspace_root):
        return workspace_root, None

    target = str(workspace_root)
    mappings = current_subst_mappings()
    for drive, mapped in mappings.items():
        try:
            if Path(mapped).resolve() == workspace_root:
                print(f"检测到现有 ASCII 路径映射：{drive}: -> {mapped}")
                return Path(f"{drive}:/"), None
        except OSError:
            pass

    for drive in FALLBACK_DRIVE_LETTERS:
        if drive not in mappings and not Path(f"{drive}:/").exists():
            subprocess.run(["cmd", "/c", "subst", f"{drive}:", target], check=True)
            print(f"已创建临时路径映射：{drive}: -> {target}")
            return Path(f"{drive}:/"), drive

    raise SystemExit("无法找到可用盘符来创建临时 ASCII 路径映射。")


def remove_subst(drive: str | None) -> None:
    if os.name == "nt" and drive:
        subprocess.run(["cmd", "/c", "subst", f"{drive}:", "/D"], check=False)
        print(f"已移除临时路径映射：{drive}:")


def first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def find_cmake(workspace_root: Path) -> str:
    candidates = list((workspace_root / "_tools").glob("cmake-*-windows-x86_64/*/bin/cmake.exe"))
    cmake = first_existing(candidates)
    if cmake:
        return str(cmake)
    found = shutil.which("cmake")
    if found:
        return found
    raise SystemExit("未找到 cmake.exe。")


def find_ninja(workspace_root: Path) -> str:
    candidates = list((workspace_root / "_tools").glob("ninja-*/ninja.exe"))
    ninja = first_existing(candidates)
    if ninja:
        return str(ninja)
    found = shutil.which("ninja")
    if found:
        return found
    raise SystemExit("未找到 ninja.exe。")


def find_toolchain(workspace_root: Path, mapped_workspace: Path) -> Path:
    candidates = [
        Path("D:/cpm_tools/xpack-arm-none-eabi-gcc-14.2.1-1.1"),
        mapped_workspace / "_tools/xpack-arm-none-eabi-gcc-14.2.1-1.1-win32-x64/xpack-arm-none-eabi-gcc-14.2.1-1.1",
        workspace_root / "_tools/xpack-arm-none-eabi-gcc-14.2.1-1.1-win32-x64/xpack-arm-none-eabi-gcc-14.2.1-1.1",
    ]
    for candidate in candidates:
        if (candidate / "bin/arm-none-eabi-gcc.exe").exists():
            return candidate
    raise SystemExit("未找到 ARM GCC 工具链。")


def ensure_picotool_runtime(workspace_root: Path, build_dir: Path) -> None:
    picotool_dirs = [build_dir / "_deps/picotool", build_dir / "_deps/picotool-build"]
    dll_source_dir = workspace_root / "_tools/llvm-mingw-20260616-ucrt-x86_64/bin"
    for picotool_dir in picotool_dirs:
        if not (picotool_dir / "picotool.exe").exists():
            continue
        for dll_name in ("libc++.dll", "libunwind.dll"):
            src = dll_source_dir / dll_name
            if src.exists():
                shutil.copy2(src, picotool_dir / dll_name)


def force_rebuild_embedded_resources(build_dir: Path, profile: AnimationProfile) -> None:
    object_dir = build_dir / "CMakeFiles/computer_performance_monitor.dir"
    object_names = (profile.object_name,) + COMMON_EMBEDDED_OBJECTS
    print("\n==== 清理嵌入资源缓存 ====")
    if not object_dir.exists():
        print("资源对象目录尚不存在，首次编译会自动生成。")
        return

    removed = 0
    for object_name in object_names:
        for suffix in ("", ".d"):
            path = object_dir / f"{object_name}{suffix}"
            if path.exists():
                path.unlink()
                removed += 1
                print(f"已删除旧资源对象：{path}")
    if removed == 0:
        print("没有发现旧资源对象，后续编译会按需生成。")
    else:
        print("已清理旧的 .incbin 汇编对象，避免 UF2 继续嵌入旧二进制资源。")


def build_firmware(repo_root: Path, profile: AnimationProfile) -> None:
    ensure_animation_project(repo_root, profile)
    workspace_root = repo_root.parent
    mapped_workspace, subst_drive = subst_workspace(workspace_root.resolve())
    try:
        mapped_repo = mapped_workspace / repo_root.name
        mapped_build = mapped_repo / "build-dgcc"
        cmake = find_cmake(mapped_workspace)
        ninja = find_ninja(mapped_workspace)
        toolchain = find_toolchain(workspace_root, mapped_workspace)

        print("\n==== 编译环境 ====")
        print(f"工程目录：{repo_root}")
        print(f"构建目录：{repo_root / 'build-dgcc'}")
        print(f"CMake：{cmake}")
        print(f"Ninja：{ninja}")
        print(f"ARM GCC：{toolchain}")

        if not (mapped_build / "build.ninja").exists():
            print("\n==== 配置 CMake 工程 ====")
            run(
                [
                    cmake,
                    "-S",
                    str(mapped_repo),
                    "-B",
                    str(mapped_build),
                    "-G",
                    "Ninja",
                    f"-DCMAKE_MAKE_PROGRAM={ninja}",
                    f"-DPICO_SDK_PATH={mapped_workspace / '_deps/pico-sdk'}",
                    f"-DFREERTOS_KERNEL_PATH={mapped_workspace / '_deps/FreeRTOS-Kernel'}",
                    f"-DPICO_TOOLCHAIN_PATH={toolchain}",
                ],
                cwd=mapped_repo,
            )

        print("\n==== 编译 UF2 固件 ====")
        force_rebuild_embedded_resources(mapped_build, profile)
        ensure_picotool_runtime(mapped_workspace, mapped_build)
        try:
            run([cmake, "--build", str(mapped_build), "--config", "Release"], cwd=mapped_repo)
        except subprocess.CalledProcessError:
            print("首次编译失败，重新补齐 picotool 运行时后再试一次。")
            ensure_picotool_runtime(mapped_workspace, mapped_build)
            run([cmake, "--build", str(mapped_build), "--config", "Release"], cwd=mapped_repo)

        uf2 = repo_root / "build-dgcc/computer_performance_monitor.uf2"
        if uf2.exists():
            print(f"UF2 已生成：{uf2}")
            print(f"UF2 大小：{uf2.stat().st_size:,} bytes ({uf2.stat().st_size / 1024 / 1024:.2f} MiB)")
    finally:
        remove_subst(subst_drive)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从逐帧图片生成启动动画 RGB565 bin，并可选编译 RP2040 UF2 固件。"
    )
    parser.add_argument("--frames", type=Path, help="逐帧图片文件夹路径。")
    parser.add_argument("--fps", type=float, help="视频帧率，单位：帧/秒。")
    parser.add_argument("--loops", type=int, help="开机时循环播放动画的次数，至少为 1。")
    parser.add_argument("--hold-ms", type=int, help="最后一帧额外停留时间，单位：毫秒；Doro 旧版动画代码会忽略此项。")
    parser.add_argument("--build", action="store_true", help="生成 bin 后直接编译 UF2。")
    parser.add_argument("--no-build", action="store_true", help="生成 bin 后不询问、不编译 UF2。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.build and args.no_build:
        raise SystemExit("不能同时使用 --build 和 --no-build。")

    repo_root = Path(__file__).resolve().parents[1]
    workspace_root = repo_root.parent
    profile = detect_animation_profile(repo_root)
    ensure_animation_project(repo_root, profile)
    header_path = repo_root / profile.header_name
    output_path = repo_root / profile.output_name

    print("==== 启动动画生成工具 ====")
    print(f"脚本位置：{Path(__file__).resolve()}")
    print(f"固件工程：{repo_root}")
    print(f"动画配置：{profile.display_name}")
    print(f"参数头文件：{header_path}")
    print(f"输出 bin：{output_path}")

    current_delay_ms = read_macro_int(header_path, profile.frame_delay_macro, 40) or 40
    current_fps = 1000.0 / current_delay_ms
    current_loops = read_macro_int(header_path, profile.repeat_count_macro, 1) or 1
    current_hold_ms = 0
    if profile.final_hold_macro:
        current_hold_ms = read_macro_int(header_path, profile.final_hold_macro, 0) or 0

    default_frames = default_frame_dir(workspace_root, profile)
    frame_folder = args.frames.expanduser().resolve() if args.frames else prompt_path(
        "请输入逐帧图片文件夹", default_frames
    )
    if not frame_folder.is_dir():
        raise SystemExit(f"逐帧图片文件夹不存在：{frame_folder}")

    fps = args.fps if args.fps is not None else prompt_float("请输入视频帧率（帧/秒）", current_fps)
    if fps <= 0:
        raise SystemExit("--fps 必须大于 0。")
    frame_delay_ms = max(1, int(round(1000.0 / fps)))

    repeat_count = args.loops if args.loops is not None else prompt_int(
        "请输入开机动画循环播放次数", current_loops, min_value=1
    )
    if repeat_count < 1:
        raise SystemExit("--loops 必须大于或等于 1。")

    if profile.final_hold_macro:
        final_hold_ms = args.hold_ms if args.hold_ms is not None else prompt_int(
            "请输入最后一帧额外停留时间（ms）", current_hold_ms, min_value=0
        )
        if final_hold_ms < 0:
            raise SystemExit("--hold-ms 必须大于或等于 0。")
    else:
        final_hold_ms = 0
        if args.hold_ms not in (None, 0):
            print("提示：当前 Doro 动画代码没有最后一帧额外停留参数，--hold-ms 将被忽略。")

    frames = find_frames(frame_folder)
    width, height, total_size = generate_rgb565_blob(frames, output_path)

    print("\n==== 播放参数 ====")
    print(f"帧率：{fps:g} fps")
    print(f"每帧延时：{frame_delay_ms} ms")
    print(f"循环次数：{repeat_count}")
    if profile.final_hold_macro:
        print(f"最后一帧额外停留：{final_hold_ms} ms")
    else:
        print("最后一帧额外停留：当前动画代码不支持")
    print(f"单轮播放时长约：{len(frames) * frame_delay_ms / 1000:.2f} 秒")
    print(f"总播放时长约：{(len(frames) * frame_delay_ms * repeat_count + final_hold_ms) / 1000:.2f} 秒")

    frame_size = width * height * 2
    update_header(
        header_path,
        profile,
        width=width,
        height=height,
        frame_count=len(frames),
        repeat_count=repeat_count,
        frame_delay_ms=frame_delay_ms,
        final_hold_ms=final_hold_ms,
        frame_size=frame_size,
        total_size=total_size,
    )
    print_flash_estimate(repo_root, output_path, total_size)

    should_build = args.build
    if not args.build and not args.no_build:
        should_build = prompt_yes_no("是否现在编译 UF2 固件？", default=False)
    if should_build:
        sys.stdout.flush()
        build_firmware(repo_root, profile)


if __name__ == "__main__":
    main()
