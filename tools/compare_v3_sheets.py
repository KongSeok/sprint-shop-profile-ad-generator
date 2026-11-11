"""Rebuild Claude v3 fixture sheets through the app renderer for visual comparison."""
import base64
import os
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.core.config import PROJECT_ROOT
from app.schemas.design import RenderDesign
from app.services.renderer import fill_html, open_browser, screenshot
from app.services.template_v3 import styles

REF = PROJECT_ROOT / "experiments/claude_templates_v3"
OUT = PROJECT_ROOT / "experiments/design_samples/sheet_comparison"


def as_url(path):
    media = "png" if path.suffix == ".png" else "jpeg"
    return f"data:image/{media};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sheets = {}
    src = (REF / "render.py").read_text(encoding="utf-8")
    fixtures, cases = src.split("import shutil", 1)
    fixtures = fixtures.replace("os.makedirs('out',exist_ok=True)", "")
    cases = cases[cases.index("AD={"):]
    original_directory = Path.cwd()
    with open_browser() as browser:
        def render(kind, name, style, palette, output, font=None, lang="ko", **values):
            for key in ("photo_url", "cutout_url"):
                if values.get(key):
                    values[key] = as_url(REF / values[key].removeprefix("../"))
            design = RenderDesign(style=style, palette=palette, font=font or next(iter(styles()[style]["fonts"])), lang=lang,
                                  ad_layout=name if kind == "ad_card" else "photo_full",
                                  menu_layout=name if kind == "menu_board" else "text_list")
            html, meta = fill_html(kind, values, template=name, design=design)
            result = screenshot(html, meta, browser=browser)
            with Image.open(BytesIO(result.png)) as image:
                sheets[output] = image.convert("RGB")

        try:
            os.chdir(REF)
            ns = {}
            exec(compile(fixtures, "claude_fixture_setup", "exec"), ns)
            ns["render"] = render
            exec(compile(cases, "claude_fixture_cases", "exec"), ns)
        finally:
            os.chdir(original_directory)

    W = 2400
    font = ImageFont.truetype(str(REF / "fonts/NotoSansKR-700.ttf"), 30)
    lang_labels = ("한글+작은 영어", "한글만", "한글+작은 영어", "영어+작은 한글")
    layout_labels = ("광고 사진형", "광고 누끼형", "메뉴판 목록형", "메뉴판 고급형")

    def row(images, height, labels):
        items = [image.resize((image.width * height // image.height, height)) for image in images]
        total = sum(image.width for image in items) + 16 * (len(items) - 1)
        if total > W:
            items = [image.resize((image.width * W // total, image.height * W // total)) for image in items]
            height = items[0].height
        canvas = Image.new("RGB", (W, height + 50), "white")
        draw = ImageDraw.Draw(canvas)
        x = (W - sum(image.width for image in items) - 16 * (len(items) - 1)) // 2
        for image, label in zip(items, labels):
            canvas.paste(image, (x, 0))
            draw.text((x + 4, height + 8), label, font=font, fill="#333")
            x += image.width + 16
        return canvas

    panels = []
    for style, options in styles().items():
        app_rows = [row([sheets[key] for key in sorted(sheets) if key.startswith(style + "_m")], 760,
                        [f"{layout} · {lang}" for layout, lang in zip(layout_labels, lang_labels)])]
        for group, prefix, height in (("palettes", "p", 380 if len(options["palettes"]) <= 6 else 290),
                                      ("fonts", "f", 520)):
            keys = options[group]
            app_rows.append(row([sheets[f"{style}_{prefix}_{key}"] for key in keys], height,
                                [item["name"] for item in keys.values()]))
        app = Image.new("RGB", (W, sum(item.height for item in app_rows) + 140), "white")
        y = 20
        for item in app_rows:
            app.paste(item, (0, y))
            y += item.height + 40
        with Image.open(REF / f"sheet_{style}.jpg") as ref:
            side = Image.new("RGB", (W * 2, max(ref.height, app.height) + 56), "white")
            side.paste(ref, (0, 56))
        side.paste(app, (W, 56))
        draw = ImageDraw.Draw(side)
        draw.text((12, 8), f"{style} · Claude", font=font, fill="#333")
        draw.text((W + 12, 8), f"{style} · 앱 렌더", font=font, fill="#333")
        side.save(OUT / f"{style}.jpg", quality=90)
        side.thumbnail((1500, 1500))
        panels.append(side)
    grid = Image.new("RGB", (1500, sum(image.height for image in panels)), "white")
    y = 0
    for image in panels:
        grid.paste(image, (0, y))
        y += image.height
    grid.save(OUT / "grid.jpg", quality=90)

    with Image.open(REF / "new_layouts.jpg") as ref:
        width, height = ref.size
        paired = Image.new("RGB", (width * 2, height), "white")
        paired.paste(ref, (0, 0))
    draw = ImageDraw.Draw(paired)
    titles = ("영수증형 광고", "큰 가격형 광고", "영수증형 메뉴판", "큰 가격형 메뉴판")
    positions = (170, 746, 1322, 1733)
    for x, title in zip(positions, titles):
        draw.text((width + x, 20), title, font=font, fill="#333")
    for i, style in enumerate(styles()):
        y = 70 + 580 * i
        draw.text((width + 10, y + 260), style, font=font, fill="#333")
        for x, key in zip(positions, sorted(key for key in sheets if key.startswith(style + "_n"))):
            image = sheets[key].copy()
            image.thumbnail((560, 560))
            paired.paste(image, (width + x, y))
    paired.save(OUT / "new_layouts_comparison.jpg", quality=90)


if __name__ == "__main__":
    main()
