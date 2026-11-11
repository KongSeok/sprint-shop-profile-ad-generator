"""Build the comparison grid and the reproducible metric table."""
import csv
from pathlib import Path
from PIL import Image

HERE = Path(__file__).resolve().parent
SETUP = """# IC-Light 음식 사진 실험

- RTX 2080 Super 8GB, 별도 Python 가상환경, PyTorch cu128, Diffusers 0.27.2, Transformers 4.36.2.
- FC/FBC 공식 데모의 추론을 사용했습니다. 코드 라이선스는 Apache-2.0이고 IC-Light 가중치는 CreativeML Open RAIL-M입니다.
- 베이스는 `stablediffusionapi/realistic-vision-v51`입니다. 기존 ISNet RGBA를 회색(127)에 합성해 조건으로 넣었습니다.
- Seed 42, 512×512 → 768×768, 25 steps, CFG 2, highres denoise 0.5. FC는 프롬프트에 맞는 left/top 초기 그라데이션, FBC는 업종별 기존 seed 42 배경을 사용했습니다.
- 원본은 ISNet 파일에 보존된 RGB입니다. 출력과 같은 LANCZOS 중앙 크롭 뒤 알파 ≥128에서만 CIE76 ΔE와 L* 평균 차이를 계산했습니다. 흑백 SSIM은 마스크 바깥을 원본으로 맞춘 뒤 SSIM 지도의 마스크 내부 평균입니다.
- 빛만 옮긴 열은 밝기 비율을 마스크로 가중해 σ=30px로 흐린 뒤 원본 RGB에 곱했습니다. 마스크 바깥은 원본입니다.
- 시간은 모델 로드와 수치 계산을 제외한 추론 시간입니다. VRAM은 `torch.cuda.max_memory_allocated` 기준 MiB입니다.
- 왼쪽부터 원본, ISNet 누끼, IC-Light, 마스크 안 ΔE 히트맵, 빛만 옮긴 결과입니다.

```powershell
# 저장소 루트에서, 실험 전용 환경
.\\.venv\\Scripts\\python.exe -m venv experiments/ic_light/.venv
$p = "experiments/ic_light/.venv/Scripts/python.exe"
& $p -m pip install torch==2.11.0+cu128 --index-url https://download.pytorch.org/whl/cu128
& $p -m pip install -r experiments/ic_light/requirements.txt
& $p experiments/ic_light/run_relight.py fc
& $p experiments/ic_light/run_relight.py fbc
& $p experiments/ic_light/build_report.py
```

`weights/`에 FC/FBC safetensors를 넣어 실행합니다. `weights/base/`는 Realistic Vision Diffusers 파일의 로컬 복사본이며 없으면 Hugging Face에서 로드합니다.

[공식 소스](https://github.com/lllyasviel/IC-Light) · [IC-Light 모델](https://huggingface.co/lllyasviel/ic-light) · [베이스 모델](https://huggingface.co/stablediffusionapi/realistic-vision-v51)
"""


def build():
    with (HERE / "metrics.csv").open(encoding="utf-8", newline="") as stream:
        rows = sorted(csv.DictReader(stream), key=lambda row: (row["photo"], ("left", "top", "fbc").index(row["mode"])))
    table = ["| 사진 | 모드 | 시간(초) | VRAM(MiB) | ΔE | SSIM | ΔL* | 빛만 ΔE | 빛만 SSIM | 빛만 ΔL* |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    grid = Image.new("RGB", (1280, len(rows) * 280), "white")
    for index, row in enumerate(rows):
        with Image.open(HERE / "results" / f"{row['photo']}_{row['mode']}.png") as panel:
            grid.paste(panel, (0, index * 280))
        metrics = [f"{float(row[key]):.3f}" for key in ("seconds", "max_vram_mib", "delta_e", "ssim", "brightness_diff",
                   "light_delta_e", "light_ssim", "light_brightness_diff")]
        table.append("| " + " | ".join([row["photo"], row["mode"], *metrics]) + " |")
    grid.save(HERE / "compare_grid.jpg", quality=94)
    report = HERE / "README.md"
    existing = report.read_text(encoding="utf-8") if report.exists() else ""
    observations = existing.partition("## 관찰")[2]
    report.write_text(SETUP + "\n" + "\n".join(table) + "\n\n## 관찰" + (observations or "\n"), encoding="utf-8")


if __name__ == "__main__":
    build()
