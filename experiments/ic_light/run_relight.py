# SPDX-License-Identifier: Apache-2.0
# Adapted from lllyasviel/IC-Light, gradio_demo.py and gradio_demo_bg.py.
# https://github.com/lllyasviel/IC-Light (see LICENSE).
"""Run the isolated IC-Light experiment using existing ISNet RGBA images."""

import argparse
import csv
import gc
import math
import os
import time
from enum import Enum
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
os.environ.setdefault("HF_HOME", str(HERE / ".cache"))

import numpy as np
import torch
import safetensors.torch as sf
from PIL import Image, ImageDraw
from diffusers import (AutoencoderKL, UNet2DConditionModel, StableDiffusionPipeline,
                       StableDiffusionImg2ImgPipeline, DPMSolverMultistepScheduler)
from transformers import CLIPTextModel, CLIPTokenizer
from scipy.ndimage import gaussian_filter
from skimage.color import rgb2lab, rgb2gray
from skimage.metrics import structural_similarity

BASE = "stablediffusionapi/realistic-vision-v51"
device = torch.device("cuda")


def load(mode):
    global tokenizer, text_encoder, vae, unet, t2i_pipe, i2i_pipe, unet_original_forward
    base = str(HERE / "weights/base") if (HERE / "weights/base").is_dir() else BASE
    tokenizer = CLIPTokenizer.from_pretrained(base, subfolder="tokenizer")
    text_encoder = CLIPTextModel.from_pretrained(base, subfolder="text_encoder").to(device, torch.float16)
    vae = AutoencoderKL.from_pretrained(base, subfolder="vae").to(device, torch.float16)
    unet = UNet2DConditionModel.from_pretrained(base, subfolder="unet")
    conv = unet.conv_in
    with torch.no_grad():
        expanded = torch.nn.Conv2d(8 if mode == "fc" else 12, conv.out_channels,
                                   conv.kernel_size, conv.stride, conv.padding)
        expanded.weight.zero_()
        expanded.weight[:, :4].copy_(conv.weight)
        expanded.bias = conv.bias
        unet.conv_in = expanded
        offsets = sf.load_file(str(HERE / "weights" / f"iclight_sd15_{mode}.safetensors"))
        for key, tensor in unet.state_dict().items():
            tensor.add_(offsets[key])
        del offsets
    unet.to(device, torch.float16)
    unet_original_forward = unet.forward
    unet.forward = hooked_unet_forward
    scheduler = DPMSolverMultistepScheduler(num_train_timesteps=1000, beta_start=.00085,
                                           beta_end=.012, beta_schedule="scaled_linear",
                                           algorithm_type="sde-dpmsolver++", use_karras_sigmas=True,
                                           steps_offset=1)
    options = dict(vae=vae, text_encoder=text_encoder, tokenizer=tokenizer, unet=unet,
                   scheduler=scheduler, safety_checker=None, feature_extractor=None,
                   requires_safety_checker=False)
    t2i_pipe = StableDiffusionPipeline(**options)
    i2i_pipe = StableDiffusionImg2ImgPipeline(**options)


def hooked_unet_forward(sample, timestep, encoder_hidden_states, **kwargs):
    c_concat = kwargs['cross_attention_kwargs']['concat_conds'].to(sample)
    c_concat = torch.cat([c_concat] * (sample.shape[0] // c_concat.shape[0]), dim=0)
    new_sample = torch.cat([sample, c_concat], dim=1)
    kwargs['cross_attention_kwargs'] = {}
    return unet_original_forward(new_sample, timestep, encoder_hidden_states, **kwargs)

@torch.inference_mode()
def encode_prompt_inner(txt: str):
    max_length = tokenizer.model_max_length
    chunk_length = tokenizer.model_max_length - 2
    id_start = tokenizer.bos_token_id
    id_end = tokenizer.eos_token_id
    id_pad = id_end

    def pad(x, p, i):
        return x[:i] if len(x) >= i else x + [p] * (i - len(x))

    tokens = tokenizer(txt, truncation=False, add_special_tokens=False)["input_ids"]
    chunks = [[id_start] + tokens[i: i + chunk_length] + [id_end] for i in range(0, len(tokens), chunk_length)]
    chunks = [pad(ck, id_pad, max_length) for ck in chunks]

    token_ids = torch.tensor(chunks).to(device=device, dtype=torch.int64)
    conds = text_encoder(token_ids).last_hidden_state

    return conds

@torch.inference_mode()
def encode_prompt_pair(positive_prompt, negative_prompt):
    c = encode_prompt_inner(positive_prompt)
    uc = encode_prompt_inner(negative_prompt)

    c_len = float(len(c))
    uc_len = float(len(uc))
    max_count = max(c_len, uc_len)
    c_repeat = int(math.ceil(max_count / c_len))
    uc_repeat = int(math.ceil(max_count / uc_len))
    max_chunk = max(len(c), len(uc))

    c = torch.cat([c] * c_repeat, dim=0)[:max_chunk]
    uc = torch.cat([uc] * uc_repeat, dim=0)[:max_chunk]

    c = torch.cat([p[None, ...] for p in c], dim=1)
    uc = torch.cat([p[None, ...] for p in uc], dim=1)

    return c, uc

@torch.inference_mode()
def pytorch2numpy(imgs, quant=True):
    if not torch.isfinite(imgs).all():
        raise FloatingPointError("Nonfinite VAE output")
    results = []
    for x in imgs:
        y = x.movedim(0, -1)

        if quant:
            y = y * 127.5 + 127.5
            y = y.detach().float().cpu().numpy().clip(0, 255).astype(np.uint8)
        else:
            y = y * 0.5 + 0.5
            y = y.detach().float().cpu().numpy().clip(0, 1).astype(np.float32)

        results.append(y)
    return results

@torch.inference_mode()
def numpy2pytorch(imgs):
    h = torch.from_numpy(np.stack(imgs, axis=0)).float() / 127.0 - 1.0  # so that 127 must be strictly 0.0
    h = h.movedim(-1, 1)
    return h

def resize_and_center_crop(image, target_width, target_height):
    pil_image = Image.fromarray(image)
    original_width, original_height = pil_image.size
    scale_factor = max(target_width / original_width, target_height / original_height)
    resized_width = int(round(original_width * scale_factor))
    resized_height = int(round(original_height * scale_factor))
    resized_image = pil_image.resize((resized_width, resized_height), Image.LANCZOS)
    left = (resized_width - target_width) / 2
    top = (resized_height - target_height) / 2
    right = (resized_width + target_width) / 2
    bottom = (resized_height + target_height) / 2
    cropped_image = resized_image.crop((left, top, right, bottom))
    return np.array(cropped_image)

def resize_without_crop(image, target_width, target_height):
    pil_image = Image.fromarray(image)
    resized_image = pil_image.resize((target_width, target_height), Image.LANCZOS)
    return np.array(resized_image)

@torch.inference_mode()
def process_fc(input_fg, prompt, image_width, image_height, num_samples, seed, steps, a_prompt, n_prompt, cfg, highres_scale, highres_denoise, lowres_denoise, bg_source):
    bg_source = BGSource(bg_source)
    input_bg = None

    if bg_source == BGSource.NONE:
        pass
    elif bg_source == BGSource.LEFT:
        gradient = np.linspace(255, 0, image_width)
        image = np.tile(gradient, (image_height, 1))
        input_bg = np.stack((image,) * 3, axis=-1).astype(np.uint8)
    elif bg_source == BGSource.RIGHT:
        gradient = np.linspace(0, 255, image_width)
        image = np.tile(gradient, (image_height, 1))
        input_bg = np.stack((image,) * 3, axis=-1).astype(np.uint8)
    elif bg_source == BGSource.TOP:
        gradient = np.linspace(255, 0, image_height)[:, None]
        image = np.tile(gradient, (1, image_width))
        input_bg = np.stack((image,) * 3, axis=-1).astype(np.uint8)
    elif bg_source == BGSource.BOTTOM:
        gradient = np.linspace(0, 255, image_height)[:, None]
        image = np.tile(gradient, (1, image_width))
        input_bg = np.stack((image,) * 3, axis=-1).astype(np.uint8)
    else:
        raise 'Wrong initial latent!'

    rng = torch.Generator(device=device).manual_seed(int(seed))

    fg = resize_and_center_crop(input_fg, image_width, image_height)

    concat_conds = numpy2pytorch([fg]).to(device=vae.device, dtype=vae.dtype)
    concat_conds = vae.encode(concat_conds).latent_dist.mode() * vae.config.scaling_factor

    conds, unconds = encode_prompt_pair(positive_prompt=prompt + ', ' + a_prompt, negative_prompt=n_prompt)

    if input_bg is None:
        latents = t2i_pipe(
            prompt_embeds=conds,
            negative_prompt_embeds=unconds,
            width=image_width,
            height=image_height,
            num_inference_steps=steps,
            num_images_per_prompt=num_samples,
            generator=rng,
            output_type='latent',
            guidance_scale=cfg,
            cross_attention_kwargs={'concat_conds': concat_conds},
        ).images.to(vae.dtype) / vae.config.scaling_factor
    else:
        bg = resize_and_center_crop(input_bg, image_width, image_height)
        bg_latent = numpy2pytorch([bg]).to(device=vae.device, dtype=vae.dtype)
        bg_latent = vae.encode(bg_latent).latent_dist.mode() * vae.config.scaling_factor
        latents = i2i_pipe(
            image=bg_latent,
            strength=lowres_denoise,
            prompt_embeds=conds,
            negative_prompt_embeds=unconds,
            width=image_width,
            height=image_height,
            num_inference_steps=int(round(steps / lowres_denoise)),
            num_images_per_prompt=num_samples,
            generator=rng,
            output_type='latent',
            guidance_scale=cfg,
            cross_attention_kwargs={'concat_conds': concat_conds},
        ).images.to(vae.dtype) / vae.config.scaling_factor

    pixels = vae.decode(latents).sample
    pixels = pytorch2numpy(pixels)
    pixels = [resize_without_crop(
        image=p,
        target_width=int(round(image_width * highres_scale / 64.0) * 64),
        target_height=int(round(image_height * highres_scale / 64.0) * 64))
    for p in pixels]

    pixels = numpy2pytorch(pixels).to(device=vae.device, dtype=vae.dtype)
    latents = vae.encode(pixels).latent_dist.mode() * vae.config.scaling_factor
    latents = latents.to(device=unet.device, dtype=unet.dtype)

    image_height, image_width = latents.shape[2] * 8, latents.shape[3] * 8

    fg = resize_and_center_crop(input_fg, image_width, image_height)
    concat_conds = numpy2pytorch([fg]).to(device=vae.device, dtype=vae.dtype)
    concat_conds = vae.encode(concat_conds).latent_dist.mode() * vae.config.scaling_factor

    latents = i2i_pipe(
        image=latents,
        strength=highres_denoise,
        prompt_embeds=conds,
        negative_prompt_embeds=unconds,
        width=image_width,
        height=image_height,
        num_inference_steps=int(round(steps / highres_denoise)),
        num_images_per_prompt=num_samples,
        generator=rng,
        output_type='latent',
        guidance_scale=cfg,
        cross_attention_kwargs={'concat_conds': concat_conds},
    ).images.to(vae.dtype) / vae.config.scaling_factor

    pixels = vae.decode(latents).sample

    return pytorch2numpy(pixels)

class BGSource(Enum):
    NONE = "None"
    LEFT = "Left Light"
    RIGHT = "Right Light"
    TOP = "Top Light"
    BOTTOM = "Bottom Light"

@torch.inference_mode()
def process_fbc(input_fg, input_bg, prompt, image_width, image_height, num_samples, seed, steps, a_prompt, n_prompt, cfg, highres_scale, highres_denoise, bg_source):
    rng = torch.Generator(device=device).manual_seed(seed)

    fg = resize_and_center_crop(input_fg, image_width, image_height)
    bg = resize_and_center_crop(input_bg, image_width, image_height)
    concat_conds = numpy2pytorch([fg, bg]).to(device=vae.device, dtype=vae.dtype)
    concat_conds = vae.encode(concat_conds).latent_dist.mode() * vae.config.scaling_factor
    concat_conds = torch.cat([c[None, ...] for c in concat_conds], dim=1)

    conds, unconds = encode_prompt_pair(positive_prompt=prompt + ', ' + a_prompt, negative_prompt=n_prompt)

    latents = t2i_pipe(
        prompt_embeds=conds,
        negative_prompt_embeds=unconds,
        width=image_width,
        height=image_height,
        num_inference_steps=steps,
        num_images_per_prompt=num_samples,
        generator=rng,
        output_type='latent',
        guidance_scale=cfg,
        cross_attention_kwargs={'concat_conds': concat_conds},
    ).images.to(vae.dtype) / vae.config.scaling_factor

    pixels = vae.decode(latents).sample
    pixels = pytorch2numpy(pixels)
    pixels = [resize_without_crop(
        image=p,
        target_width=int(round(image_width * highres_scale / 64.0) * 64),
        target_height=int(round(image_height * highres_scale / 64.0) * 64))
    for p in pixels]

    pixels = numpy2pytorch(pixels).to(device=vae.device, dtype=vae.dtype)
    latents = vae.encode(pixels).latent_dist.mode() * vae.config.scaling_factor
    latents = latents.to(device=unet.device, dtype=unet.dtype)

    image_height, image_width = latents.shape[2] * 8, latents.shape[3] * 8
    fg = resize_and_center_crop(input_fg, image_width, image_height)
    bg = resize_and_center_crop(input_bg, image_width, image_height)
    concat_conds = numpy2pytorch([fg, bg]).to(device=vae.device, dtype=vae.dtype)
    concat_conds = vae.encode(concat_conds).latent_dist.mode() * vae.config.scaling_factor
    concat_conds = torch.cat([c[None, ...] for c in concat_conds], dim=1)

    latents = i2i_pipe(
        image=latents,
        strength=highres_denoise,
        prompt_embeds=conds,
        negative_prompt_embeds=unconds,
        width=image_width,
        height=image_height,
        num_inference_steps=int(round(steps / highres_denoise)),
        num_images_per_prompt=num_samples,
        generator=rng,
        output_type='latent',
        guidance_scale=cfg,
        cross_attention_kwargs={'concat_conds': concat_conds},
    ).images.to(vae.dtype) / vae.config.scaling_factor

    pixels = vae.decode(latents).sample
    pixels = pytorch2numpy(pixels, quant=False)

    return pixels, [fg, bg]


PHOTOS = {
    "cafe_02_basque_cheesecake": "cafe",
    "korean_01_doenjang_jjigae": "korean",
    "japanese_02_ramen": "japanese",
    "meat_01_samgyeopsal_plate": "meat",
}
PROMPTS = {"left": "warm window light from left", "top": "soft studio light from top"}
OUT = HERE / "results"


def save_result(name, tag, rgba, relit, seconds, peak, precision, sliced):
    size = relit.shape[1], relit.shape[0]
    reference = resize_and_center_crop(rgba[..., :3], *size)
    cutout = resize_and_center_crop(rgba, *size)
    mask = cutout[..., 3] >= 128
    gray = rgb2gray(reference)
    relit_gray = rgb2gray(relit)
    ratio = np.clip((relit_gray + .03) / (gray + .03), .35, 2.5)
    smooth = gaussian_filter(ratio * mask, 30) / np.maximum(gaussian_filter(mask.astype(float), 30), 1e-6)
    light_only = reference.copy()
    light_only[mask] = np.clip(reference[mask] * smooth[mask, None], 0, 255).round().astype(np.uint8)

    def metrics(image):
        lab = rgb2lab(image)
        delta = np.linalg.norm(lab - rgb2lab(reference), axis=2)
        other_gray = rgb2gray(image)
        _, ssim = structural_similarity(gray, np.where(mask, other_gray, gray), data_range=1, full=True)
        return dict(delta_e=float(delta[mask].mean()), ssim=float(ssim[mask].mean()),
                    brightness_diff=float((lab[..., 0] - rgb2lab(reference)[..., 0])[mask].mean())), delta

    values, delta = metrics(relit)
    light_values, _ = metrics(light_only)
    heat = np.zeros_like(reference)
    heat[..., 0] = np.where(mask, np.minimum(delta / 50, 1) * 255, 0).astype(np.uint8)
    heat[..., 1] = (heat[..., 0] // 3)
    foreground = Image.fromarray(cutout)
    neutral = Image.new("RGB", size, "#888888")
    neutral.paste(foreground, mask=foreground.getchannel("A"))
    panels = [Image.fromarray(reference), neutral, Image.fromarray(relit), Image.fromarray(heat), Image.fromarray(light_only)]
    row = Image.new("RGB", (1280, 280), "white")
    draw = ImageDraw.Draw(row)
    for i, (panel, label) in enumerate(zip(panels, (f"{PHOTOS[name]} / {tag} / original", "ISNet", "IC-Light", "Delta E 0-50", "Light only"))):
        row.paste(panel.resize((256, 256), Image.Resampling.LANCZOS), (256 * i, 24))
        draw.text((256 * i + 4, 4), label, fill="black")
    row.save(OUT / f"{name}_{tag}.png")
    Image.fromarray(relit).save(OUT / f"{name}_{tag}_relit.png")
    path = HERE / "metrics.csv"
    record = dict(photo=name, mode=tag, seconds=seconds, max_vram_mib=peak, vae=precision, slicing=sliced,
                  **values, **{f"light_{key}": val for key, val in light_values.items()})
    with path.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(record))
        if stream.tell() == 0:
            writer.writeheader()
        writer.writerow(record)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["fc", "fbc"])
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    load(args.mode)
    print(f"Loaded {args.mode} on {torch.cuda.get_device_name()}", flush=True)
    sliced = False
    for name, category in PHOTOS.items():
        rgba = np.array(Image.open(ROOT / "experiments/image_cutout/isnet-general-use" / f"{name}.png").convert("RGBA"))
        alpha = rgba[..., 3:4].astype(np.float32) / 255
        fg = np.rint(rgba[..., :3] * alpha + 127 * (1 - alpha)).astype(np.uint8)
        path = ROOT / "experiments/image_background" / f"{category}_42.png"
        if args.mode == "fbc" and not path.exists():
            print(f"SKIP {name}: no background", flush=True)
            continue
        bg = np.array(Image.open(path).convert("RGB")) if args.mode == "fbc" else None
        for tag, prompt in PROMPTS.items() if args.mode == "fc" else [("fbc", "food photography, lighting matching the background")]:
            if (OUT / f"{name}_{tag}.png").exists():
                continue
            settings = (prompt, 512, 512, 1, 42, 25, "realistic photograph", "blurry, low quality", 2, 1.5, .5)
            while True:
                gc.collect()
                torch.cuda.empty_cache()
                torch.cuda.reset_peak_memory_stats()
                start = time.perf_counter()
                failure = None
                try:
                    if args.mode == "fc":
                        source = next(item.value for item in BGSource if item.name == tag.upper())
                        relit = process_fc(fg, *settings, .9, source)[0]
                    else:
                        relit = (process_fbc(fg, bg, *settings, None)[0][0] * 255).round().astype(np.uint8)
                    if relit.max() <= 2:
                        raise FloatingPointError("Black image")
                    torch.cuda.synchronize()
                except torch.cuda.OutOfMemoryError:
                    failure = "oom"
                except FloatingPointError:
                    failure = "precision"
                if failure == "oom" and not sliced:
                    t2i_pipe.enable_attention_slicing()
                    i2i_pipe.enable_attention_slicing()
                    sliced = True
                    print("Retry with attention slicing", flush=True)
                elif failure == "precision" and vae.dtype == torch.float16:
                    vae.to(dtype=torch.float32)
                    print("Retry with VAE fp32", flush=True)
                elif failure:
                    raise RuntimeError(f"{name}/{tag}: {failure}")
                else:
                    break
            save_result(name, tag, rgba, relit, time.perf_counter() - start,
                        torch.cuda.max_memory_allocated() / 1024**2, str(vae.dtype), sliced)
            print(f"Saved {name}/{tag}", flush=True)


if __name__ == "__main__":
    main()
