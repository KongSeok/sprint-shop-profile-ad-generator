"""Photo upload and cutout selection for the ad-card workflow."""

import base64
from hashlib import sha256
from io import BytesIO

from PIL import Image, ImageDraw
import numpy as np
import streamlit as st

from app.core.config import CUTOUT_MAX_UPLOAD_BYTES
from app.ui.api_client import UserApiError
from app.ui.labels import CUTOUT_MODES
from app.ui.state import remember
from app.services.cutout_policy import PARTIAL_HINT_RATIO
from app.services.deglare import blown_ratio, soften_highlights
from app.services.renderer import cutout_problem


def checkerboard_preview(png_base64: str) -> Image.Image:
    with Image.open(BytesIO(base64.b64decode(png_base64))) as png:
        image = png.convert("RGBA")
    image.thumbnail((720, 720), Image.Resampling.LANCZOS)
    board = Image.new("RGBA", image.size, "#f3f3f3")
    draw = ImageDraw.Draw(board)
    cell = 16
    for y in range(0, image.height, cell):
        for x in range(0, image.width, cell):
            if (x // cell + y // cell) % 2:
                draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill="#bfc3c9")
    return Image.alpha_composite(board, image).convert("RGB")


def render_cutout_preview(api, shop_id, menu_name):
    state = st.session_state
    scope = sha256(repr((shop_id, menu_name)).encode("utf-8")).hexdigest()
    key = f"cutout_upload_{scope}"
    uploads = state.setdefault("ad_uploads", {})

    def remove_upload():
        uploads.pop(scope, None)
        state.get("menu_photos", {}).get(shop_id, {}).pop(menu_name, None)
        state.pop("board_png", None)

    def update_upload():
        file = state.get(key)
        if file:
            remove_upload()
            uploads[scope] = (file.name, file.getvalue())
        else:
            remove_upload()

    photo = st.file_uploader("음식 사진 (JPG·PNG, 10MB 이하)", type=["jpg", "jpeg", "png"], key=key, on_change=update_upload)
    if photo and scope not in uploads:
        update_upload()
    if not photo and scope in uploads:
        st.caption(uploads[scope][0])
        st.button("다른 사진 올리기", key=f"remove_{scope}", on_click=remove_upload)
    upload = uploads.get(scope)
    if not upload:
        cached = state.get("quick_results", {})
        if cached.get("shop_id") == shop_id:
            item = cached["menus"].get(menu_name, {})
            if item.get("photo"):
                state.cutout_selection = item["cutout_selection"]
                result = item["photo"]
                return result["original_png_base64"], result["cutout_png_base64"]
    if not upload or len(upload[1]) > CUTOUT_MAX_UPLOAD_BYTES:
        state.pop("cutout_selection", None)
        state.pop("cutout_preview", None)
        if upload:
            st.error("사진은 10MB 이하로 올려 주세요.")
        return
    _, data = upload
    identity = (scope, sha256(data).hexdigest())
    preview = state.get("cutout_preview")
    if preview is None or preview["identity"] != identity:
        state.pop("cutout_selection", None)
        preview = {"identity": identity}
        state.cutout_preview = preview

    if "result" not in preview:
        if "error" not in preview or st.button("배경 다시 지우기"):
            try:
                with st.spinner("음식 배경을 분리하고 있어요…"):
                    preview["result"] = api(
                        "POST", "/image/cutout",
                        payload={"photo_base64": base64.b64encode(data).decode("ascii")},
                        timeout=120,
                    )
            except UserApiError as exc:
                preview["error"] = str(exc)
        if "result" not in preview:
            st.error(preview["error"])
            return

    result = preview["result"]
    cutout_png = result["cutout_png_base64"]
    with Image.open(BytesIO(base64.b64decode(cutout_png))) as png:
        pixels = np.asarray(png.convert("RGBA"))
    problem = cutout_problem("data:image/png;base64," + cutout_png, result["suggest_original"])
    if problem:
        st.caption(problem)
    if blown_ratio(pixels) >= 0.03:
        st.caption("조명 반사가 적게, 비스듬한 자연광에서 찍어 주세요")
    if remember(st.checkbox, "반사 줄이기", f"cutout_glare_{scope}_{identity[1]}", False):
        buffer = BytesIO()
        Image.fromarray(soften_highlights(pixels)).save(buffer, format="PNG")
        cutout_png = base64.b64encode(buffer.getvalue()).decode("ascii")
    suggested = result["suggest_original"] or result.get("partial_foreground_ratio", 0) >= PARTIAL_HINT_RATIO
    if suggested and result.get("reason"):
        st.info(result["reason"])
    mode = remember(st.radio,
        "배경 합성에 사용할 사진", f"cutout_choice_{scope}_{identity[1]}",
        "original" if suggested else "cutout", options=("cutout", "original"), horizontal=True,
        format_func=CUTOUT_MODES.__getitem__,
    )
    shop_photos = state.setdefault("menu_photos", {}).setdefault(shop_id, {})
    if menu_name not in shop_photos or preview.get("recorded_photo") != identity:
        with Image.open(BytesIO(base64.b64decode(result["original_png_base64"]))) as png:
            image = png.convert("RGB")
        image.thumbnail((480, 480), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=87)
        shop_photos[menu_name] = {
            "url": "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"),
            "suggest_original": bool(suggested or problem),
        }
        preview["recorded_photo"] = identity
    state.cutout_selection = {
        "mode": mode, "png_base64": cutout_png if mode == "cutout" else result["original_png_base64"],
        "suggest_original": bool(suggested or problem),
        "original_png_base64": result["original_png_base64"],
    }
    return result["original_png_base64"], cutout_png


def show_photo_preview(preview):
    original, cutout = st.columns(2)
    original.image(base64.b64decode(preview[0]), caption="원본", width="stretch")
    cutout.image(checkerboard_preview(preview[1]), caption="배경 지운 모습", width="stretch")
