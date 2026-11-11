"""Create cutout, composition, and ad-card comparisons for the food photos."""
import argparse
import base64
import json
from pathlib import Path
from zipfile import ZipFile

from app.core.config import PROJECT_ROOT
from app.services.copy_examples import business_category
from tools.background_samples import CATEGORIES, call, grid
from tools.cutout_test import EXTENSIONS, save_csv

MENU_NAMES = {
    "meat": ("삼겹살", "불판 삼겹살", "소갈비"),
    "bakery": ("호두 바게트", "에피 바게트", "크루아상"),
    "cafe": ("라테", "밤 바스크치즈케이크", "치즈케이크와 커피"),
    "korean": ("된장찌개", "소불고기와 밥", "김치찌개와 밥"),
    "japanese": ("모둠 초밥", "차슈 라멘", "연어 롤"),
}
RESIDUE = {"cafe_01": "cafe", "japanese_02": "bakery"}


def photos():
    folder = PROJECT_ROOT / "data/photos"
    paths = sorted(path for path in folder.rglob("*") if path.suffix.lower() in EXTENSIONS)
    if paths:
        for path in paths:
            yield path.stem, path.read_bytes()
        return
    with ZipFile(PROJECT_ROOT.parent / "photos.zip") as archive:
        for name in sorted(archive.namelist()):
            path = Path(name)
            if path.suffix.lower() in EXTENSIONS and not path.name.startswith("._"):
                yield path.stem, archive.read(name)


def encode(png):
    return base64.b64encode(png).decode("ascii")


def decoded(payload, key):
    data = payload.get(key)
    return base64.b64decode(data) if data else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--reuse-backgrounds", action="store_true",
                        help="Use same-seed PNGs from tools.background_samples, when available.")
    args = parser.parse_args()
    out = PROJECT_ROOT / "experiments/image_level2"
    out.mkdir(parents=True, exist_ok=True)
    shops = {}
    for line in (PROJECT_ROOT / "data/samples/answer_profiles_gold.jsonl").read_text(encoding="utf-8").splitlines():
        profile = json.loads(line)["profile"]
        shops.setdefault(business_category(profile["business_type"]), profile)

    def backdrop(key):
        path = PROJECT_ROOT / f"experiments/image_background/{key}_{args.seed}.png"
        return encode(path.read_bytes()) if args.reuse_backgrounds and path.is_file() else None

    rows, overview, residues = [], [], []
    for name, photo in photos():
        key, index, *_ = name.split("_")
        profile = shops[CATEGORIES[key]]
        cutout = call("POST", "/image/cutout", {"photo_base64": encode(photo)})
        mode = "original" if cutout["suggest_original"] else "cutout"
        payload = {"profile": profile, "mode": mode, "seed": args.seed}
        if mode == "original":
            payload["photo_base64"] = cutout["original_png_base64"]
        else:
            payload["cutout_png_base64"] = cutout["cutout_png_base64"]
            payload["background_png_base64"] = backdrop(key)
        result = call("POST", "/image/compose", payload)
        menu = MENU_NAMES[key][int(index) - 1]
        card = call("POST", "/render/ad-card", {
            "profile": profile, "menu": {"name": menu}, "headline": menu,
            "body": "메뉴 사진을 담았어요.", "template": "photo_full",
            "photo_url": "data:image/png;base64," + result["composite_png_base64"],
        })
        panels = [(name, decoded(cutout, "original_png_base64")),
                  ("Background" if mode == "cutout" else "No background", decoded(result, "background_png_base64")),
                  (f"Composite / {mode}", decoded(result, "composite_png_base64")),
                  ("Ad card", decoded(card, "png_base64"))]
        grid(out / f"{name}.png", panels, 4, tile=360)
        overview.extend(panels)
        rows.append({"photo": name, "mode": mode, "seed": result["seed"], **result["seconds"],
                     "background_reused": bool(payload.get("background_png_base64")),
                     "render_warnings": " | ".join(card["warnings"])})
        save_csv(out / "timings.csv", rows)
        print(name, mode, flush=True)

        prefix = f"{key}_{index}"
        if prefix in RESIDUE:
            for lighting, category in (("Light", RESIDUE[prefix]), ("Dark", "meat")):
                comp = call("POST", "/image/compose", {
                    "profile": {"shop_name": None, "business_type": CATEGORIES[category]}, "mode": "cutout", "seed": args.seed,
                    "cutout_png_base64": cutout["cutout_png_base64"],
                    "background_png_base64": backdrop(category),
                })
                residues.append((f"{prefix} / {lighting}", decoded(comp, "composite_png_base64")))
    if overview:
        grid(out / "grid.png", overview, 4)
    if residues:
        grid(out / "residue.png", residues, 2, tile=480)


if __name__ == "__main__":
    main()
