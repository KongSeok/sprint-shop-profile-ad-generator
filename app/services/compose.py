"""Place a cutout over a background without altering opaque food colors."""
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter, ImageOps, UnidentifiedImageError

SIZE = 1080


class InvalidComposition(ValueError):
    pass


@dataclass
class Composition:
    png: bytes
    food_bbox: tuple[int, int, int, int] | None
    food_mask_png: bytes | None


def encode_png(image):
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def read_image(data, mode):
    try:
        with Image.open(BytesIO(data)) as image:
            if max(image.size) > 8192 or image.width * image.height > 40_000_000:
                raise InvalidComposition("사진 크기가 너무 커요.")
            if mode == "RGBA" and not (image.format == "PNG" and image.mode == "RGBA"):
                raise InvalidComposition("투명 배경이 있는 RGBA 누끼 PNG를 넣어 주세요.")
            return ImageOps.exif_transpose(image).convert(mode)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise InvalidComposition("사진 파일을 읽지 못했어요.") from exc


def compose_original(photo):
    original = read_image(photo, "RGB")
    covered = ImageOps.fit(original, (SIZE, SIZE), Image.Resampling.LANCZOS)
    return Composition(encode_png(covered), None, None)


def compose_cutout(cutout, background, width_ratio=0.62):
    food = read_image(cutout, "RGBA")
    bbox = food.getchannel("A").point(lambda alpha: 255 if alpha >= 16 else 0).getbbox()
    if bbox is None:
        raise InvalidComposition("누끼에 남은 음식이 없어요. 사진 그대로를 써 주세요.")
    food = food.crop(bbox)
    scale = min(1.0, SIZE * width_ratio / food.width, SIZE * 0.55 / food.height)
    if scale < 1:
        food = food.resize((max(1, round(food.width * scale)), max(1, round(food.height * scale))),
                           Image.Resampling.LANCZOS)

    canvas = read_image(background, "RGB").resize((SIZE, SIZE), Image.Resampling.LANCZOS).convert("RGBA")
    x = (SIZE - food.width) // 2
    y = round(SIZE * 0.51 - food.height / 2)
    bottom = y + food.height

    shadow = Image.new("RGBA", canvas.size)
    ImageDraw.Draw(shadow).ellipse(
        (x + food.width * 0.08, bottom - 24, x + food.width * 0.92, bottom + 14),
        fill=(0, 0, 0, 105),
    )
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
    canvas.alpha_composite(food, (x, y))
    mask = Image.new("L", canvas.size)
    mask.paste(food.getchannel("A"), (x, y))
    return Composition(encode_png(canvas.convert("RGB")), (x, y, x + food.width, bottom), encode_png(mask))
