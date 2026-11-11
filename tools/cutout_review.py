"""Review existing RGBA cutouts on two backgrounds and test tiny-island removal."""

import argparse
import csv
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import label


BACKGROUNDS = ("#f3f3f3", "#21242b")
REVIEW_PHOTOS = {
    "cafe_01_latte", "japanese_02_ramen", "japanese_01_nigiri", "korean_03_kimchi_jjigae",
}


def remove_small_components(image, max_fraction):
    alpha = np.asarray(image.getchannel("A"))
    labels, _ = label(alpha >= 16, structure=np.ones((3, 3)))
    areas = np.bincount(labels.ravel())
    areas[0] = 0
    largest = int(areas.max())
    small = (areas > 0) & (areas < largest * max_fraction)
    removed = small[labels]
    result = image.copy()
    result.putalpha(Image.fromarray(np.where(removed, 0, alpha).astype("uint8")))
    assert np.array_equal(np.asarray(result)[..., :3], np.asarray(image)[..., :3])
    assert np.array_equal(np.asarray(result.getchannel("A"))[~removed], alpha[~removed])
    return result, largest, int(small.sum()), int(removed.sum())


def comparison(path, panels):
    width = 420
    canvas = Image.new("RGB", (width * len(panels), 454), "#eeeeee")
    draw = ImageDraw.Draw(canvas)
    for i, (name, image, color) in enumerate(panels):
        preview = Image.alpha_composite(Image.new("RGBA", image.size, color), image)
        preview.thumbnail((width, width))
        canvas.paste(preview, (i * width + (width - preview.width) // 2, 34 + (width - preview.height) // 2))
        draw.text((i * width + 12, 10), name, fill="black")
    canvas.save(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("experiments/image_cutout_postprocess/isnet-raw"))
    parser.add_argument("--output", type=Path, default=Path("experiments/image_cutout_review"))
    parser.add_argument("--max-component-fraction", type=float, default=0.005)
    args = parser.parse_args()
    if not 0 < args.max_component_fraction < 1:
        parser.error("Component fraction must be between 0 and 1")
    paths = sorted(args.raw_dir.glob("*.png"))
    if not paths:
        parser.error(f"No raw masks in {args.raw_dir}")
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    for path in paths:
        with Image.open(path) as saved:
            if saved.mode != "RGBA":
                raise ValueError(f"Expected RGBA: {path}")
            image = saved.copy()
        cleaned, largest, count, pixels = remove_small_components(image, args.max_component_fraction)
        records.append(dict(photo=path.stem, largest=largest, removed_components=count, removed_pixels=pixels))
        comparison(args.output / f"{path.stem}_components.png", [
            (f"{stage} / {tone}", candidate, color)
            for tone, color in zip(("light", "dark"), BACKGROUNDS)
            for stage, candidate in (("Before", image), ("After", cleaned))
        ])
        if path.stem in REVIEW_PHOTOS:
            comparison(args.output / f"{path.stem}_backgrounds.png", [
                ("Light background", image, BACKGROUNDS[0]), ("Dark background", image, BACKGROUNDS[1]),
            ])
    with (args.output / "components.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)


if __name__ == "__main__":
    main()
