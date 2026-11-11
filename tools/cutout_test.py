"""Compare rembg masks without changing any source RGB values."""

import argparse
from collections import Counter
import csv
import io
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import sys
import tempfile
from time import perf_counter
from zipfile import ZipFile

import numpy as np
from PIL import Image, ImageDraw, ImageOps


ROOT = Path(__file__).resolve().parents[1]
if not __package__:
    sys.path.insert(0, str(ROOT))
MODELS = ("u2net", "isnet-general-use")
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
CUDA = "CUDAExecutionProvider"


def verify_png(path, source):
    with Image.open(path) as saved:
        if saved.mode != "RGBA" or saved.size != source.size:
            raise ValueError(f"Unexpected PNG format or dimensions: {path}")
        pixels = np.asarray(saved)
        changed = np.any(pixels[..., :3] != np.asarray(source), axis=2)
        visible = pixels[..., 3] > 0
        if np.any(changed):
            raise ValueError(f"RGB changed at {np.count_nonzero(changed)} pixels "
                             f"({np.count_nonzero(changed & visible)} visible): {path}")
        return int(np.count_nonzero(visible))


def write_comparison(path, panels, labels=("Original", *MODELS)):
    cell_width = 480
    heading = 34
    previews = []
    for panel in panels:
        preview = panel.convert("RGBA")
        preview.thumbnail((cell_width, cell_width), Image.Resampling.LANCZOS)
        previews.append(preview)
    height = max(preview.height for preview in previews)
    canvas = Image.new("RGB", (cell_width * 3, height + heading), "#f8f8f8")
    draw = ImageDraw.Draw(canvas)
    for index, (label, preview) in enumerate(zip(labels, previews)):
        x0 = index * cell_width
        draw.text((x0 + 12, 10), label, fill="black")
        for y in range(0, height, 16):
            for x in range(0, cell_width, 16):
                if (x // 16 + y // 16) % 2:
                    draw.rectangle((x0 + x, heading + y, x0 + x + 15, heading + y + 15), fill="#cfcfcf")
        canvas.paste(preview, (x0 + (cell_width - preview.width) // 2,
                              heading + (height - preview.height) // 2), preview)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)


def save_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def provider_counts(profile_path, expected):
    events = json.loads(Path(profile_path).read_text(encoding="utf-8"))
    runs = sorted((event for event in events if event.get("name") == "model_run"),
                  key=lambda event: event["ts"])
    if len(runs) != expected:
        raise RuntimeError(f"Expected {expected} profiled model runs, found {len(runs)}")
    kernels = [event for event in events if event.get("cat") == "Node"
               and event.get("args", {}).get("provider")]
    counts = []
    for run in runs:
        start = run["ts"]
        end = start + run["dur"]
        counts.append(Counter(event["args"]["provider"] for event in kernels if start <= event["ts"] <= end))
    if any(not count for count in counts):
        raise RuntimeError("ONNX profiling did not record a kernel provider")
    return counts


def load_photos(folder, zip_path):
    if zip_path:
        with ZipFile(zip_path) as archive:
            photos = []
            for member in archive.infolist():
                name = PurePosixPath(member.filename)
                if member.is_dir() or name.suffix.lower() not in EXTENSIONS or "__MACOSX" in name.parts:
                    continue
                if name.is_absolute() or any(
                    part.endswith((".", " ")) or PureWindowsPath(part).is_reserved()
                    or any(char in '<>:"\\|?*' or ord(char) < 32 for char in part)
                    for part in name.parts
                ):
                    raise ValueError(f"Unsafe ZIP member path: {name}")
                photos.append((name.as_posix(), archive.read(member)))
            return sorted(photos, key=lambda item: item[0])
    return [(path.relative_to(folder).as_posix(), path) for path in sorted(folder.rglob("*"))
            if path.is_file() and path.suffix.lower() in EXTENSIONS]


def read_source(data):
    with Image.open(io.BytesIO(data) if isinstance(data, bytes) else data) as image:
        return ImageOps.exif_transpose(image).convert("RGB")


def run(photos, output, *, compare_postprocess=False):
    from app.services.cutout import apply_mask
    from app.services.cutout_policy import DEFAULT_CUTOUT_MODEL, DEFAULT_POST_PROCESS_MASK, suggest_original_preview

    os.environ.setdefault("U2NET_HOME", str(ROOT / ".cache" / "rembg"))
    import torch  # Preload CUDA/cuDNN DLLs for ONNX Runtime on Windows.
    import onnxruntime as ort
    from rembg import new_session, remove

    requested = [CUDA, "CPUExecutionProvider"] if torch.cuda.is_available() else ["CPUExecutionProvider"]
    output.mkdir(parents=True, exist_ok=True)
    loads = []
    timings = []
    variants = (
        ((DEFAULT_CUTOUT_MODEL, "isnet-raw", DEFAULT_POST_PROCESS_MASK),
         (DEFAULT_CUTOUT_MODEL, "isnet-postprocess", True))
        if compare_postprocess else tuple((model, model, False) for model in MODELS)
    )
    for model, variant, postprocess in variants:
        with tempfile.TemporaryDirectory(dir=output) as scratch:
            options = ort.SessionOptions()
            options.enable_profiling = True
            options.profile_file_prefix = str(Path(scratch) / "ort")
            cache = Path(os.environ["U2NET_HOME"])
            cached = any(path.is_file() for path in
                         (cache / f"{model}.onnx", cache / "models" / model / f"{model}.onnx"))
            start = perf_counter()
            session = new_session(model, sess_opts=options, providers=requested)
            load_seconds = perf_counter() - start
            providers = session.inner_session.get_providers()
            loads.append({"model": model, "variant": variant, "session_init_seconds": round(load_seconds, 4),
                          "weights_cached_before_load": cached, "session_providers": "|".join(providers)})
            save_csv(output / "model_load.csv", loads)
            print(f"{model}: initialized in {load_seconds:.3f}s ({', '.join(providers)})", flush=True)
            rows = []
            try:
                for index, (name, data) in enumerate(photos):
                    start = perf_counter()
                    source = read_source(data)
                    path = output / variant / Path(name).with_suffix(".png")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    mask_start = perf_counter()
                    mask = remove(source.copy(), session=session, only_mask=True, post_process_mask=postprocess).convert("L")
                    inference_seconds = perf_counter() - mask_start
                    apply_mask(source, mask).save(path)
                    visible = verify_png(path, source)
                    alpha = np.asarray(mask)
                    foreground = np.count_nonzero(alpha >= 16)
                    partial = np.count_nonzero((alpha >= 16) & (alpha < 240))
                    rows.append({"model": model, "variant": variant, "photo": name, "first_image": index == 0,
                                 "suggest_original_preview": (not postprocess and model == DEFAULT_CUTOUT_MODEL and
                                     suggest_original_preview(foreground / alpha.size, partial / max(foreground, 1))),
                                 "foreground_ratio": round(foreground / alpha.size, 4),
                                 "partial_foreground_ratio": round(partial / max(foreground, 1), 4),
                                 "mask_seconds": round(inference_seconds, 4),
                                 "total_seconds": round(perf_counter() - start, 4),
                                 "alpha_nonzero_pixels": visible, "rgb_preserved": True})
            finally:
                profile = session.inner_session.end_profiling()
            for row, counts in zip(rows, provider_counts(profile, len(rows))):
                row["cuda_used"] = counts[CUDA] > 0
                row["cuda_kernels"] = counts[CUDA]
                row["cpu_kernels"] = counts["CPUExecutionProvider"]
            timings.extend(rows)
            save_csv(output / "timings.csv", timings)
            del session
    first_variant, second_variant = [variant for _, variant, _ in variants]
    for name, data in photos:
        relative = Path(name).with_suffix(".png")
        with Image.open(output / first_variant / relative) as first, Image.open(output / second_variant / relative) as second:
            write_comparison(output / "comparison" / relative, (read_source(data), first, second),
                             ("Original", first_variant, second_variant))
    print(f"Verified {len(timings)} RGBA PNGs. Results: {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photos", type=Path, default=ROOT / "data" / "photos")
    parser.add_argument("--zip", type=Path, help="Read photos from a ZIP without extracting it")
    parser.add_argument("--output", type=Path, default=ROOT / "experiments" / "image_cutout")
    parser.add_argument("--compare-postprocess", action="store_true", help="Compare ISNet before and after rembg mask post-processing")
    args = parser.parse_args()
    if args.zip and not args.zip.is_file():
        parser.error(f"Photo archive not found: {args.zip}")
    photos = load_photos(args.photos, args.zip)
    if not photos:
        parser.error(f"No photos found in {args.zip or args.photos}")
    names = [str(Path(name).with_suffix(".png")).casefold() for name, _ in photos]
    if len(names) != len(set(names)):
        parser.error("Multiple photos map to the same output PNG name")
    run(photos, args.output, compare_postprocess=args.compare_postprocess)


if __name__ == "__main__":
    main()
