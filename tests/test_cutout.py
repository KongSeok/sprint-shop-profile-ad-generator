import base64
from io import BytesIO

import pytest
from PIL import Image, ImageChops

from app.services import cutout
from app.services.cutout_policy import analyze_mask


@pytest.mark.parametrize(
    ("alpha", "suggested", "foreground", "partial"),
    [
        ([128] * 4, True, 1.0, 1.0),
        ([0, 255, 0, 255], False, 0.5, 0.0),
        # A fully opaque mask covering the frame triggers the coverage threshold.
        ([255] * 4, True, 1.0, 0.0),
        ([15, 16, 239, 240, 255], True, 0.8, 0.5),
    ],
)
def test_raw_mask_signal(alpha, suggested, foreground, partial):
    mask = Image.frombytes("L", (len(alpha), 1), bytes(alpha))
    result = analyze_mask(mask)
    assert result["suggest_original"] is suggested
    assert bool(result["reason"]) is suggested
    assert result["foreground_ratio"] == foreground
    assert result["partial_foreground_ratio"] == partial


def test_prepare_rgb_applies_exif_before_resize(monkeypatch):
    monkeypatch.setattr(cutout.config, "CUTOUT_MAX_EDGE", 8)
    source = Image.new("RGB", (12, 6))
    exif = source.getexif()
    exif[274] = 6
    stream = BytesIO()
    source.save(stream, format="JPEG", exif=exif)
    assert cutout.prepare_rgb(stream.getvalue()).size == (4, 8)


def test_cutout_endpoint_keeps_rgb_and_returns_both_options(api_client, monkeypatch):
    monkeypatch.setattr(cutout.config, "CUTOUT_MAX_EDGE", 3)
    source = Image.new("RGB", (6, 4), (200, 50, 10))
    source.putpixel((0, 0), (1, 2, 3))
    stream = BytesIO()
    source.save(stream, format="PNG")
    data = stream.getvalue()

    def predict(rgb):
        assert rgb.size == (3, 2)
        return Image.new("L", rgb.size, 128)

    monkeypatch.setattr(cutout, "predict_raw_mask", predict)
    response = api_client.post("/image/cutout", json={"photo_base64": base64.b64encode(data).decode()})
    assert response.status_code == 200
    result = response.json()
    assert result["suggest_original"] and result["partial_foreground_ratio"] == 1.0
    expected = cutout.prepare_rgb(data)
    for field, mode in (("original_png_base64", "RGB"), ("cutout_png_base64", "RGBA")):
        with Image.open(BytesIO(base64.b64decode(result[field]))) as image:
            assert image.mode == mode
            assert ImageChops.difference(image.convert("RGB"), expected).getbbox() is None
            if mode == "RGBA":
                assert image.getchannel("A").getextrema() == (128, 128)


@pytest.mark.parametrize("data", ["not base64", "bm90IGFuIGltYWdl"])
def test_cutout_endpoint_rejects_invalid_upload(api_client, data):
    assert api_client.post("/image/cutout", json={"photo_base64": data}).status_code == 422
