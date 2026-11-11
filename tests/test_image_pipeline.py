import base64
from io import BytesIO
from unittest.mock import Mock

from fastapi.testclient import TestClient
from PIL import Image, ImageOps
import pytest

from app.api import main
from app.core import config
from app.services import compose, image_models

PROFILE = {"shop_name": None, "business_type": "베이커리", "mood_strengths": "아늑한, 모던, 따뜻한, 정겨운, 미확인상징"}


def png(mode, size, color):
    return compose.encode_png(Image.new(mode, size, color))


def encode(data):
    return base64.b64encode(data).decode()


@pytest.fixture
def image_client(monkeypatch):
    monkeypatch.setattr(main, "init_db", lambda: None)

    def client(enabled):
        monkeypatch.setattr(config, "IMAGE_ENABLED", enabled)
        return TestClient(main.app)

    return client


def test_startup_once_and_prompt(image_client, monkeypatch):
    def generate(profile, seed, steps):
        return image_models.Background(
            png("RGB", (512, 512), "black"), seed, image_models.background_prompt(profile),
            image_models.NEGATIVE_PROMPT, 0.2, 500,
        )

    loader = Mock(return_value=Mock(generate=Mock(side_effect=generate), cpu_offload=False))
    monkeypatch.setattr(image_models, "load_background_model", loader)
    with image_client(True) as client:
        payload = {"profile": PROFILE, "seed": 0}
        one, two = [client.post("/image/background", json=payload).json() for _ in range(2)]
        assert one == two
        assert one["seed"] == 0
        assert one["prompt"].endswith("cozy, modern minimal, warm light")
        assert "pale oak" in one["prompt"]
        assert "welcoming" not in one["prompt"]
        assert "미확인상징" not in one["prompt"]
        assert set(one["negative_prompt"].split(", ")) == set(
            "food dish plate bowl cup meat bread text letters logo watermark people person hands fingers".split()
        )
        health = client.get("/health").json()
        assert health["image_loaded"] and health["image_enabled"]
        assert health["image_load_seconds"] >= 0
    loader.assert_called_once()
    assert loader.return_value.generate.call_count == 2


def test_original_available_without_model(image_client, monkeypatch):
    loader = Mock()
    monkeypatch.setattr(image_models, "load_background_model", loader)
    with image_client(False) as client:
        result = client.post("/image/background", json={"profile": PROFILE})
        assert result.status_code == 503
        assert result.json()["detail"] == image_models.DISABLED
        payload = {"profile": PROFILE, "mode": "original",
                   "photo_base64": encode(png("RGB", (20, 10), "red"))}
        result = client.post("/image/compose", json=payload)
        assert result.status_code == 200
        assert result.json()["background_png_base64"] is None
        assert result.json()["seconds"]["background"] == 0
        result = client.post("/image/compose", json={"profile": PROFILE, "mode": "cutout",
                             "cutout_png_base64": encode(png("RGBA", (10, 10), "red"))})
        assert result.status_code == 503
    loader.assert_not_called()


def test_supplied_background_skips_generation(image_client, monkeypatch):
    loader = Mock(return_value=Mock())
    monkeypatch.setattr(image_models, "load_background_model", loader)
    with image_client(True) as client:
        background = encode(png("RGB", (512, 512), "black"))
        result = client.post("/image/compose", json={
            "profile": PROFILE, "mode": "cutout", "seed": 42,
            "cutout_png_base64": encode(png("RGBA", (30, 40), "red")),
            "background_png_base64": background,
        })
        assert result.status_code == 200
        assert result.json()["background_png_base64"] == background
        assert result.json()["seconds"]["background"] == 0
        assert result.json()["food_mask_png_base64"]
    loader.return_value.generate.assert_not_called()


@pytest.mark.parametrize("size", [(30, 40), (1000, 800)])
def test_food_rgb_at_opaque_mask(size):
    food = Image.new("RGBA", size, (25, 75, 129, 255))
    food.putpixel((0, 0), (200, 150, 100, 80))
    result = compose.compose_cutout(compose.encode_png(food), png("RGB", (512, 512), "white"))
    x, y, right, bottom = result.food_bbox
    assert round(1080 * .22) <= y <= bottom <= round(1080 * .8)
    assert right - x <= size[0]
    output = Image.open(BytesIO(result.png)).crop(result.food_bbox)
    mask = Image.open(BytesIO(result.food_mask_png)).crop(result.food_bbox)
    expected = food.resize(output.size, Image.Resampling.LANCZOS)
    assert list(mask.get_flattened_data()) == list(expected.getchannel("A").get_flattened_data())
    assert all(a != 255 or actual == source[:3]
               for a, actual, source in zip(mask.get_flattened_data(), output.get_flattened_data(), expected.get_flattened_data()))


def test_original_matches_cover_crop():
    image = Image.new("RGB", (1300, 1080), "red")
    image.paste("green", (110, 0, 1190, 1080))
    result = compose.compose_original(compose.encode_png(image))
    expected = ImageOps.fit(image, (1080, 1080), Image.Resampling.LANCZOS)
    assert Image.open(BytesIO(result.png)).tobytes() == expected.tobytes()
    assert result.food_bbox is None and result.food_mask_png is None


def test_generation_oom_clears_cache_and_returns_503(image_client, monkeypatch):
    from contextlib import nullcontext

    class OutOfMemory(RuntimeError):
        pass

    torch = Mock(inference_mode=nullcontext)
    torch.cuda.OutOfMemoryError = OutOfMemory
    pipeline = Mock(side_effect=OutOfMemory)
    loader = Mock(return_value=image_models.BackgroundModel(pipeline, torch, False))
    monkeypatch.setattr(image_models, "load_background_model", loader)
    with image_client(True) as client:
        result = client.post("/image/background", json={"profile": PROFILE})
    assert result.status_code == 503
    assert result.json()["detail"] == image_models.GPU_OOM
    torch.cuda.reset_peak_memory_stats.assert_called_once()
    torch.cuda.empty_cache.assert_called_once()


def test_photo_full_route_passes_composite_url(image_client, monkeypatch):
    from app.services import renderer

    renderer_mock = Mock(return_value=renderer.RenderResult(b"card", []))
    monkeypatch.setattr(renderer, "render_ad_card", renderer_mock)
    photo_url = "data:image/png;base64," + encode(png("RGB", (1080, 1080), "red"))
    with image_client(False) as client:
        result = client.post("/render/ad-card", json={
            "profile": PROFILE, "menu": {"name": "빵"}, "headline": "빵", "body": "소개",
            "template": "photo_full", "photo_url": photo_url,
        })
    assert result.status_code == 200
    assert renderer_mock.call_args.args[2]["photo_url"] == photo_url
    assert renderer_mock.call_args.args[3] == "photo_full"
