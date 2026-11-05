import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from PIL import Image, ImageEnhance, ImageOps, UnidentifiedImageError


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
LOG_DIR = BASE_DIR / "logs"
LOG_PATH = LOG_DIR / "process.log"

SUPPORTED_INPUT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
SUPPORTED_WATERMARK_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".psd"}
SUPPORTED_POSITIONS = {
    "top_left",
    "top_right",
    "bottom_left",
    "bottom_right",
    "center",
    "tile",
}
SUPPORTED_BLEND_MODES = {
    "normal",
    "screen",
    "multiply",
    "overlay",
    "soft_light",
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "input_dir": "input",
    "output_dir": "output",
    "watermark_dir": "watermarks",
    "output_width": 800,
    "output_height": 800,
    "background_color": [255, 255, 255],
    "transparent_background": False,
    "output_format": "jpg",
    "jpeg_quality": 95,
    "margin_ratio": 0.08,
    "keep_aspect_ratio": True,
    "auto_crop_subject": True,
    "output_suffix": "_result",
    "log_path": "logs/process.log",
    "rembg_model": "u2net",
    "post_process_mask": True,
    "alpha_matting": False,
    "alpha_matting_foreground_threshold": 240,
    "alpha_matting_background_threshold": 10,
    "alpha_matting_erode_size": 10,
    "watermarks": [],
}


class AgentArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        if "--json" in sys.argv:
            result = {
                "status": "error",
                "error": message,
                "summary": {"total": 0, "success": 0, "failed": 0, "skipped": 0},
                "outputs": [],
                "failures": [],
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            raise SystemExit(2)
        super().error(message)


def load_config(config_path: Path = CONFIG_PATH) -> Dict[str, Any]:
    """Load config.json and merge it with defaults."""
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with config_path.open("r", encoding="utf-8") as file:
        user_config = json.load(file)

    config = DEFAULT_CONFIG.copy()
    config.update(user_config)
    config["_base_dir"] = config_path.parent
    return config


def resolve_config_path(config: Dict[str, Any], value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return Path(config["_base_dir"]) / path


def setup_dirs(config: Dict[str, Any]) -> None:
    for key in ("input_dir", "output_dir", "watermark_dir"):
        resolve_config_path(config, config[key]).mkdir(parents=True, exist_ok=True)
    resolve_config_path(config, str(config.get("log_path", "logs/process.log"))).parent.mkdir(
        parents=True, exist_ok=True
    )


def setup_logging(log_path: Path = LOG_PATH, quiet: bool = False) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = logging.FileHandler(log_path, mode="w", encoding="utf-8-sig")
    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)

    if not quiet:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)


def validate_config(config: Dict[str, Any]) -> None:
    output_width = int(config["output_width"])
    output_height = int(config["output_height"])
    margin_ratio = float(config["margin_ratio"])
    output_format = str(config["output_format"]).lower()

    if output_width <= 0 or output_height <= 0:
        raise ValueError("output_width 和 output_height 必须大于 0")
    if not 0 <= margin_ratio < 0.5:
        raise ValueError("margin_ratio 必须在 0 到 0.5 之间")
    if output_format not in {"jpg", "jpeg", "png", "webp"}:
        raise ValueError("output_format 仅支持 jpg、jpeg、png、webp")
    if not isinstance(config["background_color"], list) or len(config["background_color"]) not in {
        3,
        4,
    }:
        raise ValueError("background_color 必须是 RGB 或 RGBA 数组，例如 [255, 255, 255]")


def parse_color(value: str) -> List[int]:
    try:
        color = json.loads(value)
        if isinstance(color, list):
            return [int(item) for item in color]
    except json.JSONDecodeError:
        pass

    parts = [part.strip() for part in value.split(",") if part.strip()]
    if len(parts) not in {3, 4}:
        raise argparse.ArgumentTypeError("颜色必须是 R,G,B 或 R,G,B,A，例如 255,255,255")
    return [int(part) for part in parts]


def parse_watermark(value: str) -> Dict[str, Any]:
    try:
        watermark = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"水印必须是 JSON 对象: {exc}") from exc
    if not isinstance(watermark, dict):
        raise argparse.ArgumentTypeError("水印必须是 JSON 对象")
    return watermark


def apply_cli_overrides(config: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    override_pairs = {
        "input_dir": args.input_dir,
        "output_dir": args.output_dir,
        "watermark_dir": args.watermark_dir,
        "output_width": args.output_width,
        "output_height": args.output_height,
        "output_format": args.output_format,
        "jpeg_quality": args.jpeg_quality,
        "margin_ratio": args.margin_ratio,
        "background_color": args.background_color,
        "transparent_background": args.transparent_background,
        "output_suffix": args.output_suffix,
        "log_path": args.log_path,
    }

    for key, value in override_pairs.items():
        if value is not None:
            config[key] = value

    if args.watermarks_json:
        try:
            watermarks = json.loads(args.watermarks_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"--watermarks-json 不是合法 JSON: {exc}") from exc
        if not isinstance(watermarks, list):
            raise ValueError("--watermarks-json 必须是数组")
        config["watermarks"] = watermarks

    if args.watermark:
        config["watermarks"] = args.watermark

    if args.watermark_path:
        watermark = {
            "enabled": True,
            "path": args.watermark_path,
            "position": args.watermark_position,
            "scale_ratio": args.watermark_scale_ratio,
            "opacity": args.watermark_opacity,
            "margin": args.watermark_margin,
            "blend_mode": args.watermark_blend_mode,
        }
        config["watermarks"] = [watermark]

    return config


def path_to_string(path: Path) -> str:
    return str(path.resolve())


def collect_images(input_dir: Path) -> List[Path]:
    images: List[Path] = []
    if not input_dir.exists():
        return images

    for path in sorted(input_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in SUPPORTED_INPUT_EXTENSIONS:
            images.append(path)
    return images


def create_rembg_backend(config: Dict[str, Any]) -> Tuple[Any, Callable[..., Image.Image]]:
    try:
        from rembg import new_session, remove as rembg_remove
    except SystemExit as exc:
        raise RuntimeError(
            "rembg 后端不可用。请确认已安装 requirements.txt 中固定的 onnxruntime 版本。"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"rembg 导入失败: {exc}") from exc

    try:
        session = new_session(str(config.get("rembg_model", "u2net")))
    except Exception as exc:
        raise RuntimeError(f"rembg session 创建失败: {exc}") from exc

    return session, rembg_remove


def remove_background(
    image: Image.Image,
    session: Any,
    rembg_remove: Callable[..., Image.Image],
    config: Dict[str, Any],
) -> Image.Image:
    result = rembg_remove(
        image,
        session=session,
        post_process_mask=bool(config["post_process_mask"]),
        alpha_matting=bool(config["alpha_matting"]),
        alpha_matting_foreground_threshold=int(config["alpha_matting_foreground_threshold"]),
        alpha_matting_background_threshold=int(config["alpha_matting_background_threshold"]),
        alpha_matting_erode_size=int(config["alpha_matting_erode_size"]),
    )
    return result.convert("RGBA")


def crop_subject_by_alpha(image: Image.Image) -> Image.Image:
    if image.mode != "RGBA":
        image = image.convert("RGBA")

    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return image
    return image.crop(bbox)


def normalize_color(color: Iterable[int], transparent: bool = False) -> Tuple[int, int, int, int]:
    values = [max(0, min(255, int(value))) for value in color]
    if len(values) == 3:
        values.append(0 if transparent else 255)
    return tuple(values[:4])  # type: ignore[return-value]


def fit_subject_to_canvas(subject: Image.Image, config: Dict[str, Any]) -> Image.Image:
    output_width = int(config["output_width"])
    output_height = int(config["output_height"])
    margin_ratio = float(config["margin_ratio"])
    transparent_background = bool(config.get("transparent_background", False))
    background_color = normalize_color(config["background_color"], transparent_background)

    canvas = Image.new("RGBA", (output_width, output_height), background_color)

    if subject.mode != "RGBA":
        subject = subject.convert("RGBA")

    if bool(config["auto_crop_subject"]):
        subject = crop_subject_by_alpha(subject)

    max_width = max(1, int(output_width * (1 - margin_ratio * 2)))
    max_height = max(1, int(output_height * (1 - margin_ratio * 2)))

    if subject.width == 0 or subject.height == 0:
        return canvas

    if bool(config["keep_aspect_ratio"]):
        ratio = min(max_width / subject.width, max_height / subject.height)
        target_width = max(1, int(subject.width * ratio))
        target_height = max(1, int(subject.height * ratio))
        subject = subject.resize((target_width, target_height), Image.Resampling.LANCZOS)
    else:
        subject = subject.resize((max_width, max_height), Image.Resampling.LANCZOS)

    x = (output_width - subject.width) // 2
    y = (output_height - subject.height) // 2
    canvas.alpha_composite(subject, (x, y))
    return canvas


def load_psd_as_image(path: Path) -> Optional[Image.Image]:
    try:
        from psd_tools import PSDImage  # type: ignore
    except ImportError:
        logging.error("PSD 水印需要额外安装 psd-tools，已跳过: %s", path)
        return None

    try:
        psd = PSDImage.open(path)

        # Try to skip solid-color fill layers (typical PSD template backgrounds)
        # and composite only effect layers onto a transparent canvas
        import numpy as np

        effect_layers = []
        has_solid_layer = False

        for layer in psd.descendants():
            if not layer.visible or not layer.is_visible():
                continue
            composite = layer.composite()
            if composite is None:
                continue
            composite = composite.convert("RGBA")
            arr = np.array(composite)
            r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]

            # Detect solid fill: all opaque pixels are the same color
            opaque_mask = a > 0
            if opaque_mask.sum() > 0:
                opaque_colors = arr[opaque_mask][:, :3]
                if opaque_colors.max() == opaque_colors.min():
                    # All opaque pixels are the same color — likely a fill layer
                    has_solid_layer = True
                    continue

            effect_layers.append(composite)

        if effect_layers:
            canvas = Image.new("RGBA", (psd.width, psd.height), (0, 0, 0, 0))
            for layer_img in effect_layers:
                canvas.alpha_composite(layer_img)
            return canvas

        # Fallback: use psd.composite() as before
        image = psd.composite()
        if image is None:
            logging.error("PSD 水印无法合成可用图像，已跳过: %s", path)
            return None
        return image.convert("RGBA")
    except Exception as exc:
        logging.error("PSD 水印读取失败，已跳过: %s，原因: %s", path, exc)
        return None


def load_watermark_image(path: Path) -> Optional[Image.Image]:
    if not path.exists():
        logging.error("水印文件不存在，已跳过: %s", path)
        return None

    if path.suffix.lower() not in SUPPORTED_WATERMARK_EXTENSIONS:
        logging.error("水印格式不支持，已跳过: %s", path)
        return None

    if path.suffix.lower() == ".psd":
        return load_psd_as_image(path)

    try:
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            return image.convert("RGBA")
    except (UnidentifiedImageError, OSError) as exc:
        logging.error("水印文件读取失败，已跳过: %s，原因: %s", path, exc)
        return None


def resize_watermark(watermark: Image.Image, canvas_size: Tuple[int, int], scale_ratio: float) -> Image.Image:
    canvas_width, _ = canvas_size
    target_width = max(1, int(canvas_width * scale_ratio))
    ratio = target_width / watermark.width
    target_height = max(1, int(watermark.height * ratio))
    return watermark.resize((target_width, target_height), Image.Resampling.LANCZOS)


def apply_opacity(watermark: Image.Image, opacity: float) -> Image.Image:
    watermark = watermark.copy()
    alpha = watermark.getchannel("A")
    import numpy as np

    alpha_arr = np.array(alpha, dtype=float)
    # For non-normal blend modes, low-alpha watermarks (e.g. PSD light effects)
    # need amplification so opacity > 1.0 scales alpha beyond original values.
    alpha_arr = np.clip(alpha_arr * opacity, 0, 255).astype(np.uint8)
    watermark.putalpha(Image.fromarray(alpha_arr))
    return watermark


def make_light_background_transparent(watermark: Image.Image) -> Image.Image:
    """Turn the near-white background of a watermark template into alpha.

    The default Tmall-style watermark is exported as a full white square with
    pale grey diagonal marks. If tiled as-is, the white square creates visible
    blocks on product images. This converts only the light background to
    transparent while keeping the grey marks/logos.
    """
    import numpy as np

    watermark = watermark.convert("RGBA")
    arr = np.array(watermark, dtype=np.float32)
    rgb = arr[:, :, :3]
    original_alpha = arr[:, :, 3] / 255.0
    luminance = rgb[:, :, 0] * 0.299 + rgb[:, :, 1] * 0.587 + rgb[:, :, 2] * 0.114

    # White/near-white pixels become transparent; pale grey marks retain alpha.
    mark_alpha = np.clip((250.0 - luminance) / 45.0, 0.0, 1.0)
    arr[:, :, 3] = original_alpha * mark_alpha * 255.0
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode="RGBA")


def apply_full_canvas_watermark(
    image: Image.Image,
    watermark: Image.Image,
    opacity: float,
    blend_mode: str,
) -> Image.Image:
    """Apply a full-canvas watermark pattern without visible tile blocks."""
    result = image.copy()
    watermark = make_light_background_transparent(watermark)
    watermark = watermark.resize(result.size, Image.Resampling.LANCZOS)
    watermark = apply_opacity(watermark, opacity)
    return blend_images(result, watermark, blend_mode, (0, 0))


def get_watermark_position(
    position: str, canvas_size: Tuple[int, int], watermark_size: Tuple[int, int], margin: int
) -> Tuple[int, int]:
    canvas_width, canvas_height = canvas_size
    watermark_width, watermark_height = watermark_size

    if position == "top_left":
        return margin, margin
    if position == "top_right":
        return canvas_width - watermark_width - margin, margin
    if position == "bottom_left":
        return margin, canvas_height - watermark_height - margin
    if position == "bottom_right":
        return canvas_width - watermark_width - margin, canvas_height - watermark_height - margin
    if position == "center":
        return (canvas_width - watermark_width) // 2, (canvas_height - watermark_height) // 2

    raise ValueError(f"不支持的水印位置: {position}")


def blend_images(base: Image.Image, overlay: Image.Image, mode: str, offset: Tuple[int, int]) -> Image.Image:
    """Blend overlay onto base at offset using the specified blend mode."""
    if mode == "normal":
        base.alpha_composite(overlay, offset)
        return base

    import numpy as np

    # Crop base region that overlaps with overlay
    x, y = offset
    ow, oh = overlay.size
    bw, bh = base.size

    # Calculate overlap region
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(bw, x + ow)
    y2 = min(bh, y + oh)

    if x1 >= x2 or y1 >= y2:
        return base

    # Offset into overlay
    ox1 = x1 - x
    oy1 = y1 - y
    ox2 = ox1 + (x2 - x1)
    oy2 = oy1 + (y2 - y1)

    # Get overlay region, convert to RGB float
    overlay_region = overlay.crop((ox1, oy1, ox2, oy2)).convert("RGBA")
    overlay_a = np.array(overlay_region.getchannel("A"), dtype=float) / 255.0
    overlay_rgb = np.array(overlay_region.convert("RGB"), dtype=float)
    overlay_a3 = overlay_a[:, :, np.newaxis]

    # Get base region
    base_region = base.crop((x1, y1, x2, y2)).convert("RGBA")
    base_a = np.array(base_region.getchannel("A"), dtype=float) / 255.0
    base_rgb = np.array(base_region.convert("RGB"), dtype=float)
    base_a3 = base_a[:, :, np.newaxis]

    # Apply blend mode to RGB
    if mode == "screen":
        # Screen blend brightens the base. For PSD light effect layers,
        # psd_tools exports dark RGB + low alpha (the original screen-mode
        # layer data). The alpha channel IS the light intensity map.
        # Use alpha as a direct brightness boost: where alpha is high,
        # the image gets brighter, approaching white.
        blended = base_rgb + (255 - base_rgb) * overlay_a3
    elif mode == "multiply":
        blended = base_rgb * (1 - overlay_a3) + base_rgb * overlay_rgb / 255 * overlay_a3
    elif mode == "overlay":
        blended = np.where(
            base_rgb < 128,
            2 * base_rgb * overlay_rgb / 255,
            255 - 2 * (255 - base_rgb) * (255 - overlay_rgb) / 255,
        )
    elif mode == "soft_light":
        blended = np.where(
            overlay_rgb <= 128,
            base_rgb - (255 - 2 * overlay_rgb) * base_rgb * (255 - base_rgb) / (255 * 255),
            base_rgb + (2 * overlay_rgb - 255) * (np.sqrt(base_rgb / 255) * 255 - base_rgb),
        )
    else:
        blended = overlay_rgb

    blended = np.clip(blended, 0, 255)

    # For screen mode, alpha was already used as brightness intensity in the
    # blend calculation above. Apply the result directly onto the base.
    if mode == "screen":
        out_rgb = np.clip(blended, 0, 255).astype(np.uint8)
        out_a = np.clip(base_a * 255, 0, 255).astype(np.uint8)
    else:
        out_a = base_a + overlay_a * (1 - base_a)
        out_a_safe = np.where(out_a > 0, out_a, 1)[:, :, np.newaxis]
        out_rgb = (base_rgb * base_a3 * (1 - overlay_a3) + blended * overlay_a3) / out_a_safe
        out_rgb = np.clip(out_rgb, 0, 255).astype(np.uint8)
        out_a = np.clip(out_a * 255, 0, 255).astype(np.uint8)

    # Write back
    result_region = Image.fromarray(
        np.dstack([out_rgb, out_a]), mode="RGBA"
    )
    base.paste(result_region, (x1, y1))
    return base


def apply_single_watermark(
    image: Image.Image, watermark_config: Dict[str, Any], config: Dict[str, Any]
) -> Image.Image:
    if not bool(watermark_config.get("enabled", True)):
        return image

    watermark_path_value = watermark_config.get("path")
    if not watermark_path_value:
        logging.error("水印配置缺少 path，已跳过: %s", watermark_config)
        return image

    watermark_path = resolve_config_path(config, str(watermark_path_value))
    position = str(watermark_config.get("position", "tile")).lower()
    if position not in SUPPORTED_POSITIONS:
        logging.error("水印位置不支持，已跳过: %s", position)
        return image

    scale_ratio = max(0.01, float(watermark_config.get("scale_ratio", 0.2)))
    opacity = float(watermark_config.get("opacity", 1.0))
    margin = max(0, int(watermark_config.get("margin", 30)))
    blend_mode = str(watermark_config.get("blend_mode", "normal")).lower()
    if blend_mode not in SUPPORTED_BLEND_MODES:
        logging.error("水印混合模式不支持，已跳过: %s", blend_mode)
        return image

    watermark = load_watermark_image(watermark_path)
    if watermark is None:
        return image

    if watermark.width == 0 or watermark.height == 0:
        logging.error("水印尺寸无效，已跳过: %s", watermark_path)
        return image

    result = image.copy()

    if position == "tile":
        result = apply_full_canvas_watermark(result, watermark, opacity, blend_mode)
    else:
        watermark = resize_watermark(watermark, result.size, scale_ratio)
        watermark = apply_opacity(watermark, opacity)
        x, y = get_watermark_position(position, result.size, watermark.size, margin)
        result = blend_images(result, watermark, blend_mode, (x, y))

    return result


def apply_watermarks(image: Image.Image, config: Dict[str, Any]) -> Image.Image:
    result = image.convert("RGBA")
    watermarks = config.get("watermarks", [])
    if not isinstance(watermarks, list):
        logging.error("watermarks 配置必须是数组，已跳过所有水印")
        return result

    for watermark_config in watermarks:
        if not isinstance(watermark_config, dict):
            logging.error("水印配置项必须是对象，已跳过: %s", watermark_config)
            continue
        result = apply_single_watermark(result, watermark_config, config)

    return result


def build_output_path(input_path: Path, config: Dict[str, Any]) -> Path:
    output_dir = resolve_config_path(config, config["output_dir"])
    suffix = str(config.get("output_suffix", "_result"))
    output_format = str(config["output_format"]).lower()
    extension = "jpg" if output_format == "jpeg" else output_format
    return output_dir / f"{input_path.stem}{suffix}.{extension}"


def flatten_to_background(image: Image.Image, config: Dict[str, Any]) -> Image.Image:
    background_color = normalize_color(config["background_color"], transparent=False)
    background = Image.new("RGBA", image.size, background_color)
    background.alpha_composite(image.convert("RGBA"))
    return background


def save_result(image: Image.Image, output_path: Path, config: Dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_format = str(config["output_format"]).lower()
    transparent_background = bool(config.get("transparent_background", False))

    if output_format in {"jpg", "jpeg"}:
        image_to_save = flatten_to_background(image, config).convert("RGB")
        image_to_save.save(output_path, "JPEG", quality=int(config["jpeg_quality"]), optimize=True)
        return

    if output_format == "png":
        image_to_save = image.convert("RGBA") if transparent_background else flatten_to_background(image, config)
        image_to_save.save(output_path, "PNG")
        return

    if output_format == "webp":
        image_to_save = image.convert("RGBA") if transparent_background else flatten_to_background(image, config).convert("RGB")
        image_to_save.save(output_path, "WEBP", quality=int(config["jpeg_quality"]), method=6)
        return

    raise ValueError(f"不支持的输出格式: {output_format}")


def process_one_image(
    input_path: Path,
    session: Any,
    rembg_remove: Callable[..., Image.Image],
    config: Dict[str, Any],
) -> Path:
    output_path = build_output_path(input_path, config)

    with Image.open(input_path) as image:
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGBA")

    cutout = remove_background(image, session, rembg_remove, config)
    standard_image = fit_subject_to_canvas(cutout, config)
    watermarked_image = apply_watermarks(standard_image, config)
    save_result(watermarked_image, output_path, config)
    return output_path


def build_result(
    status: str,
    config_path: Path,
    config: Optional[Dict[str, Any]] = None,
    log_path: Optional[Path] = None,
    started_at: Optional[str] = None,
    ended_at: Optional[str] = None,
    total: int = 0,
    success_count: int = 0,
    failed_count: int = 0,
    skipped_count: int = 0,
    outputs: Optional[List[Dict[str, str]]] = None,
    failures: Optional[List[Dict[str, str]]] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "status": status,
        "started_at": started_at,
        "ended_at": ended_at,
        "config_path": path_to_string(config_path),
        "log_path": path_to_string(log_path or LOG_PATH),
        "summary": {
            "total": total,
            "success": success_count,
            "failed": failed_count,
            "skipped": skipped_count,
        },
        "outputs": outputs or [],
        "failures": failures or [],
    }

    if config is not None:
        result["input_dir"] = path_to_string(resolve_config_path(config, config["input_dir"]))
        result["output_dir"] = path_to_string(resolve_config_path(config, config["output_dir"]))
        result["output_format"] = str(config["output_format"]).lower()
        result["output_width"] = int(config["output_width"])
        result["output_height"] = int(config["output_height"])

    if error:
        result["error"] = error

    return result


def parse_args() -> argparse.Namespace:
    parser = AgentArgumentParser(description="本地图片批量抠图、白底标准化和水印处理工具")
    parser.add_argument(
        "--config",
        default=str(CONFIG_PATH),
        help="配置文件路径，默认使用项目目录下的 config.json",
    )
    parser.add_argument("--input-dir", help="覆盖配置中的 input_dir")
    parser.add_argument("--output-dir", help="覆盖配置中的 output_dir")
    parser.add_argument("--watermark-dir", help="覆盖配置中的 watermark_dir")
    parser.add_argument("--output-width", type=int, help="覆盖输出宽度")
    parser.add_argument("--output-height", type=int, help="覆盖输出高度")
    parser.add_argument("--output-format", choices=["jpg", "jpeg", "png", "webp"], help="覆盖输出格式")
    parser.add_argument("--jpeg-quality", type=int, help="覆盖 JPG/WEBP 质量")
    parser.add_argument("--margin-ratio", type=float, help="覆盖主体留白比例")
    parser.add_argument("--background-color", type=parse_color, help="覆盖背景色，例如 255,255,255")
    parser.add_argument(
        "--transparent-background",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="覆盖是否保留透明背景",
    )
    parser.add_argument("--output-suffix", help="覆盖输出文件名后缀")
    parser.add_argument("--log-path", help="覆盖日志路径")
    parser.add_argument(
        "--watermark",
        action="append",
        type=parse_watermark,
        help="追加水印 JSON 对象；如果提供，将替换配置文件中的 watermarks，可重复传入",
    )
    parser.add_argument("--watermarks-json", help="用 JSON 数组覆盖配置文件中的 watermarks")
    parser.add_argument("--watermark-path", help="用简单参数设置单个水印路径，适合 agent 调用")
    parser.add_argument(
        "--watermark-position",
        default="tile",
        choices=sorted(SUPPORTED_POSITIONS),
        help="配合 --watermark-path 使用的水印位置",
    )
    parser.add_argument(
        "--watermark-scale-ratio",
        type=float,
        default=0.18,
        help="配合 --watermark-path 使用的水印缩放比例",
    )
    parser.add_argument(
        "--watermark-opacity",
        type=float,
        default=0.55,
        help="配合 --watermark-path 使用的水印透明度",
    )
    parser.add_argument(
        "--watermark-margin",
        type=int,
        default=80,
        help="配合 --watermark-path 使用的水印边距",
    )
    parser.add_argument(
        "--watermark-blend-mode",
        default="normal",
        choices=sorted(SUPPORTED_BLEND_MODES),
        help="配合 --watermark-path 使用的水印混合模式",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="在 stdout 输出机器可读 JSON 结果，适合 agent 调用",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="不向控制台输出日志；日志仍写入文件。使用 --json 时自动启用",
    )
    return parser.parse_args()


def get_log_path_from_config(config_path: Path, args: argparse.Namespace) -> Path:
    if args.log_path:
        log_path = Path(args.log_path)
        return log_path if log_path.is_absolute() else config_path.parent / log_path

    if config_path.exists():
        try:
            with config_path.open("r", encoding="utf-8") as file:
                raw_config = json.load(file)
            log_path_value = raw_config.get("log_path")
            if log_path_value:
                log_path = Path(log_path_value)
                return log_path if log_path.is_absolute() else config_path.parent / log_path
        except Exception:
            pass

    return LOG_PATH


def run(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = BASE_DIR / config_path

    log_path = get_log_path_from_config(config_path, args)
    setup_logging(log_path, quiet=args.quiet or args.json)

    started_at = datetime.now().isoformat(timespec="seconds")
    logging.info("图片批处理开始: %s", started_at)

    try:
        config = load_config(config_path)
        config = apply_cli_overrides(config, args)
        if args.log_path:
            log_path = resolve_config_path(config, str(config["log_path"]))
        validate_config(config)
        setup_dirs(config)
    except Exception as exc:
        logging.exception("初始化失败: %s", exc)
        ended_at = datetime.now().isoformat(timespec="seconds")
        return 2, build_result(
            "error",
            config_path=config_path,
            log_path=log_path,
            started_at=started_at,
            ended_at=ended_at,
            error=str(exc),
        )

    input_dir = resolve_config_path(config, config["input_dir"])
    images = collect_images(input_dir)
    logging.info("输入目录: %s", input_dir)
    logging.info("共发现 %d 张图片", len(images))

    if not images:
        logging.info("没有找到可处理图片，程序结束")
        ended_at = datetime.now().isoformat(timespec="seconds")
        return 0, build_result(
            "ok",
            config_path=config_path,
            config=config,
            log_path=log_path,
            started_at=started_at,
            ended_at=ended_at,
            total=0,
        )

    try:
        session, rembg_remove = create_rembg_backend(config)
    except Exception as exc:
        logging.exception("%s", exc)
        ended_at = datetime.now().isoformat(timespec="seconds")
        return 3, build_result(
            "error",
            config_path=config_path,
            config=config,
            log_path=log_path,
            started_at=started_at,
            ended_at=ended_at,
            total=len(images),
            error=str(exc),
        )

    success_count = 0
    failed_count = 0
    outputs: List[Dict[str, str]] = []
    failures: List[Dict[str, str]] = []

    for index, image_path in enumerate(images, start=1):
        logging.info("开始处理 [%d/%d]: %s", index, len(images), image_path.name)
        try:
            output_path = process_one_image(image_path, session, rembg_remove, config)
            success_count += 1
            outputs.append(
                {
                    "input": path_to_string(image_path),
                    "output": path_to_string(output_path),
                    "filename": output_path.name,
                }
            )
            logging.info("处理成功: %s -> %s", image_path.name, output_path)
        except Exception as exc:
            failed_count += 1
            failures.append({"input": path_to_string(image_path), "error": str(exc)})
            logging.exception("处理失败: %s，原因: %s", image_path, exc)

    logging.info("图片批处理结束")
    logging.info("成功: %d，失败: %d，总数: %d", success_count, failed_count, len(images))

    ended_at = datetime.now().isoformat(timespec="seconds")
    status = "ok" if failed_count == 0 else "partial_success"
    exit_code = 0 if failed_count == 0 else 10
    return exit_code, build_result(
        status,
        config_path=config_path,
        config=config,
        log_path=log_path,
        started_at=started_at,
        ended_at=ended_at,
        total=len(images),
        success_count=success_count,
        failed_count=failed_count,
        outputs=outputs,
        failures=failures,
    )


def main() -> None:
    args = parse_args()
    exit_code, result = run(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
