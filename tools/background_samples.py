"""Save six shop backdrops for each of two fixed seeds."""
import argparse
import base64
from io import BytesIO
import os

from PIL import Image, ImageDraw, ImageOps
import requests

from app.core.config import API_BASE_URL, PROJECT_ROOT
from tools.cutout_test import save_csv

CATEGORIES = {"meat": "고깃집", "bakery": "빵집", "cafe": "카페",
              "korean": "한식", "japanese": "일식", "default": "기본"}


def call(method, path, payload=None):
    response = requests.request(method, os.getenv("IMAGE_SAMPLE_API", API_BASE_URL) + path,
                                json=payload, timeout=320)
    if not response.ok:
        raise RuntimeError(f"{path}: HTTP {response.status_code} {response.json().get('detail')}")
    return response.json()


def grid(path, entries, columns, tile=240):
    row_height = tile + 28
    rows = (len(entries) + columns - 1) // columns
    canvas = Image.new("RGB", (columns * tile, rows * row_height), "#f6f6f6")
    draw = ImageDraw.Draw(canvas)
    for index, (label, png) in enumerate(entries):
        x, y = (index % columns) * tile, (index // columns) * row_height
        draw.text((x + 8, y + 6), label, fill="black")
        if png:
            with Image.open(BytesIO(png)) as image:
                fitted = ImageOps.contain(ImageOps.exif_transpose(image).convert("RGB"), (tile, tile))
                canvas.paste(fitted, (x + (tile - fitted.width) // 2, y + 28 + (tile - fitted.height) // 2))
    canvas.save(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, nargs=2, default=(42, 43))
    args = parser.parse_args()
    out = PROJECT_ROOT / "experiments/image_background"
    out.mkdir(parents=True, exist_ok=True)
    health = call("GET", "/health")
    rows, entries = [], []
    for key, category in CATEGORIES.items():
        for seed in args.seeds:
            result = call("POST", "/image/background", {"profile": {"shop_name": None, "business_type": category}, "seed": seed})
            png = base64.b64decode(result["png_base64"])
            name = f"{key}_{seed}.png"
            (out / name).write_bytes(png)
            entries.append((f"{key} / seed {seed}", png))
            rows.append({"file": name, "category": category, "seed": seed, "seconds": result["seconds"],
                         "max_vram_mb": result["max_vram_mb"], "load_seconds": health["image_load_seconds"],
                         "cpu_offload": health["image_cpu_offload"]})
            save_csv(out / "timings.csv", rows)
            print(name, round(result["seconds"], 2), flush=True)
    grid(out / "grid.png", entries, 2, tile=300)


if __name__ == "__main__":
    main()
