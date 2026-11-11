"""Create a cutout by attaching a raw ISNet alpha mask to prepared RGB pixels."""

import base64
from functools import lru_cache
from io import BytesIO
import os
from threading import Lock

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core import config
from app.services.cutout_policy import analyze_mask


class InvalidPhoto(ValueError):
    pass


class CutoutUnavailable(RuntimeError):
    pass


_inference_lock = Lock()


def prepare_rgb(data: bytes) -> Image.Image:
    if len(data) > config.CUTOUT_MAX_UPLOAD_BYTES:
        raise InvalidPhoto("사진은 10MB 이하로 올려 주세요.")
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format not in {"JPEG", "PNG"}:
                raise InvalidPhoto("JPEG 또는 PNG 사진을 올려 주세요.")
            rgb = ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError) as exc:
        raise InvalidPhoto("사진을 읽을 수 없어요. JPEG 또는 PNG 파일을 확인해 주세요.") from exc
    if max(rgb.size) > config.CUTOUT_MAX_EDGE:
        rgb.thumbnail((config.CUTOUT_MAX_EDGE,) * 2, Image.Resampling.LANCZOS)
    return rgb


def apply_mask(rgb: Image.Image, mask: Image.Image) -> Image.Image:
    if rgb.mode != "RGB" or mask.mode != "L" or rgb.size != mask.size:
        raise ValueError("Expected RGB source and a same-size L mask")
    cutout = rgb.copy()
    cutout.putalpha(mask)
    return cutout


@lru_cache(maxsize=1)
def _load_session():
    import torch  # Preload CUDA and cuDNN DLLs for ONNX Runtime on Windows.
    from rembg import new_session

    os.environ.setdefault("U2NET_HOME", str(config.PROJECT_ROOT / ".cache" / "rembg"))
    providers = ["CPUExecutionProvider"]
    if torch.cuda.is_available():
        providers.insert(0, "CUDAExecutionProvider")
    return new_session(config.CUTOUT_MODEL, providers=providers)


def predict_raw_mask(rgb: Image.Image) -> Image.Image:
    try:
        from rembg import remove

        with _inference_lock:
            return remove(rgb.copy(), session=_load_session(), only_mask=True,
                          post_process_mask=config.CUTOUT_POST_PROCESS_MASK).convert("L")
    except (ImportError, OSError, RuntimeError) as exc:
        raise CutoutUnavailable("누끼 모델을 사용할 수 없어요. 이미지 패키지와 모델 파일을 확인해 주세요.") from exc


def _png_base64(image: Image.Image) -> str:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def create_cutout(data: bytes) -> dict:
    rgb = prepare_rgb(data)
    raw_mask = predict_raw_mask(rgb)
    return {
        **analyze_mask(raw_mask),
        "original_png_base64": _png_base64(rgb),
        "cutout_png_base64": _png_base64(apply_mask(rgb, raw_mask)),
    }
