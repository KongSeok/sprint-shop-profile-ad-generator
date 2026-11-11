from base64 import b64encode
from io import BytesIO

from PIL import Image
from streamlit.testing.v1 import AppTest


def _preview_app(original, cutout):
    from base64 import b64decode
    import streamlit as st
    from app.ui.cutout_preview import render_cutout_preview

    def api(method, path, *, payload, timeout):
        assert (method, path) == ("POST", "/image/cutout")
        st.session_state.calls = st.session_state.get("calls", 0) + 1
        suggested = b64decode(payload["photo_base64"]) == b"galbi"
        return {
            "suggest_original": suggested,
            "reason": "원본도 확인해 주세요." if suggested else None,
            "original_png_base64": original,
            "cutout_png_base64": cutout,
        }

    render_cutout_preview(api, 1, "메뉴")


def test_upload_default_switch_rerun_and_removal():
    def png(mode):
        buffer = BytesIO()
        Image.new(mode, (2, 2)).save(buffer, format="PNG")
        return b64encode(buffer.getvalue()).decode("ascii")

    original, cutout = png("RGB"), png("RGBA")
    app = AppTest.from_function(_preview_app, args=(original, cutout)).run()
    app.file_uploader[0].upload("galbi.jpg", b"galbi", "image/jpeg").run()
    assert not app.exception
    assert app.radio[0].value == "original"
    assert app.session_state["cutout_selection"]["mode"] == "original"
    assert app.session_state["cutout_selection"]["png_base64"] == original
    assert app.session_state["cutout_selection"]["suggest_original"]
    assert app.info[0].value == "원본도 확인해 주세요."

    app.radio[0].set_value("cutout").run()
    assert app.session_state["cutout_selection"]["mode"] == "cutout"
    assert app.session_state["cutout_selection"]["png_base64"] == cutout
    assert app.session_state["calls"] == 1

    app.file_uploader[0].clear().upload("epi.jpg", b"epi", "image/jpeg").run()
    assert not app.exception
    assert app.radio[0].value == "cutout"
    assert not app.info
    assert app.session_state["calls"] == 2

    app.file_uploader[0].clear().run()
    assert "cutout_selection" not in app.session_state
