"""SD 1.5 generates an empty backdrop from curated text only."""
import json
import secrets
from dataclasses import dataclass
from io import BytesIO
from threading import Lock
from time import perf_counter

from PIL import Image

from app.core.config import PROJECT_ROOT
from app.services.copy_examples import business_category

MODEL_ID = "stable-diffusion-v1-5/stable-diffusion-v1-5"
NEGATIVE_PROMPT = "food, dish, plate, bowl, cup, meat, bread, text, letters, logo, watermark, people, person, hands, fingers"
MOODS = {
    "아늑한": "cozy", "모던": "modern minimal", "따뜻한": "warm light",
    "정겨운": "welcoming", "깔끔한": "clean styling", "차분한": "calm",
    "활기찬": "vibrant atmosphere", "편안한": "relaxed atmosphere",
    "소박한": "understated", "고급스러운": "elegant", "빈티지": "vintage",
    "밝은": "bright lighting", "은은한": "soft lighting",
    "자연스러운": "natural styling", "전통": "traditional decor",
}
DISABLED = "이미지 모델이 꺼져 있어요"
GPU_OOM = "GPU 메모리가 부족해요. 사진 그대로를 써 주세요"


class ImageUnavailable(RuntimeError):
    pass


def empty_background(png):
    """Reject abrupt dark bars and strong, localized contours near either side."""
    with Image.open(BytesIO(png)) as image:
        gray = image.convert('L').resize((96, 96), Image.Resampling.BILINEAR)
    pixels = gray.load()
    for side in (1, -1):
        def shade(x, y):
            return pixels[x if side == 1 else 95 - x, y]
        for x in range(2, 24):
            if sum(shade(x, y) < 48 and shade(x + 3, y) - shade(x, y) > 45
                   for y in range(96)) >= 57:
                return False
        for top in range(0, 80, 8):
            edges = sum(abs(shade(x + 2, y) - shade(x, y)) > 42 or
                        abs(shade(x, y + 2) - shade(x, y)) > 42
                        for y in range(top, top + 16) for x in range(1, 22))
            if edges >= 38:
                return False
    return True


def generate_empty_background(model, profile, seed=None, steps=None):
    for attempt in range(3):
        current_seed = seed if attempt == 0 or seed is None else (seed + attempt) % 2**32
        result = model.generate(profile, current_seed) if steps is None else model.generate(profile, current_seed, steps)
        if empty_background(result.png):
            return result
    raise ImageUnavailable('배경 가장자리가 비어 있는 이미지를 만들지 못했어요. 사진 그대로를 써 주세요.')


def background_prompt(profile):
    prompts = json.loads((PROJECT_ROOT / "templates/image_prompts.json").read_text(encoding="utf-8"))
    category = business_category(profile.business_type)
    mood = profile.mood_strengths or ""
    additions = [english for korean, english in MOODS.items() if korean in mood][:3]
    return ", ".join([prompts.get(category, prompts["기본"]), *additions])


@dataclass
class Background:
    png: bytes
    seed: int
    prompt: str
    negative_prompt: str
    seconds: float
    max_vram_mb: float


class BackgroundModel:
    def __init__(self, pipeline, torch, cpu_offload):
        self.pipeline = pipeline
        self.torch = torch
        self.cpu_offload = cpu_offload
        self.lock = Lock()

    def generate(self, profile, seed=None, steps=25):
        torch = self.torch
        prompt = background_prompt(profile)
        seed = secrets.randbits(32) if seed is None else seed
        with self.lock:
            started = perf_counter()
            try:
                torch.cuda.reset_peak_memory_stats()
                generator = torch.Generator(device="cpu").manual_seed(seed)
                with torch.inference_mode():
                    image = self.pipeline(
                        prompt=prompt, negative_prompt=NEGATIVE_PROMPT, generator=generator,
                        width=512, height=512, num_inference_steps=steps,
                    ).images[0]
                peak = torch.cuda.max_memory_allocated() / (1024 ** 2)
            except torch.cuda.OutOfMemoryError:
                pass
            else:
                output = BytesIO()
                image.save(output, format="PNG")
                return Background(output.getvalue(), seed, prompt, NEGATIVE_PROMPT, perf_counter() - started, peak)
            torch.cuda.empty_cache()
            raise ImageUnavailable(GPU_OOM)


def load_background_model(cpu_offload=False):
    import torch
    from diffusers import StableDiffusionPipeline

    if not torch.cuda.is_available():
        raise ImageUnavailable("배경 생성에 CUDA GPU가 필요해요.")
    pipeline = StableDiffusionPipeline.from_pretrained(
        MODEL_ID, dtype=torch.float16, variant="fp16", use_safetensors=True,
        safety_checker=None, requires_safety_checker=False,
    )
    pipeline.enable_attention_slicing()
    if not cpu_offload:
        try:
            pipeline.to("cuda")
        except torch.cuda.OutOfMemoryError:
            cpu_offload = True
    if cpu_offload:
        pipeline.to("cpu")
        pipeline.enable_model_cpu_offload()
        torch.cuda.empty_cache()
    return BackgroundModel(pipeline, torch, cpu_offload)
