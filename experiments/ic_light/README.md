# IC-Light 음식 사진 실험

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
.\.venv\Scripts\python.exe -m venv experiments/ic_light/.venv
$p = "experiments/ic_light/.venv/Scripts/python.exe"
& $p -m pip install torch==2.11.0+cu128 --index-url https://download.pytorch.org/whl/cu128
& $p -m pip install -r experiments/ic_light/requirements.txt
& $p experiments/ic_light/run_relight.py fc
& $p experiments/ic_light/run_relight.py fbc
& $p experiments/ic_light/build_report.py
```

`weights/`에 FC/FBC safetensors를 넣어 실행합니다. `weights/base/`는 Realistic Vision Diffusers 파일의 로컬 복사본이며 없으면 Hugging Face에서 로드합니다.

[공식 소스](https://github.com/lllyasviel/IC-Light) · [IC-Light 모델](https://huggingface.co/lllyasviel/ic-light) · [베이스 모델](https://huggingface.co/stablediffusionapi/realistic-vision-v51)

| 사진 | 모드 | 시간(초) | VRAM(MiB) | ΔE | SSIM | ΔL* | 빛만 ΔE | 빛만 SSIM | 빛만 ΔL* |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| cafe_02_basque_cheesecake | left | 9.516 | 3443.594 | 45.831 | 0.492 | -28.777 | 27.388 | 0.755 | -22.467 |
| cafe_02_basque_cheesecake | top | 9.642 | 3443.594 | 27.100 | 0.691 | -22.515 | 22.325 | 0.857 | -20.658 |
| cafe_02_basque_cheesecake | fbc | 9.583 | 3808.460 | 26.178 | 0.858 | -13.485 | 13.489 | 0.954 | -13.320 |
| japanese_02_ramen | left | 9.603 | 3443.594 | 35.458 | 0.424 | -22.715 | 26.052 | 0.777 | -18.578 |
| japanese_02_ramen | top | 9.498 | 3443.594 | 29.530 | 0.557 | -20.856 | 22.917 | 0.833 | -18.829 |
| japanese_02_ramen | fbc | 9.141 | 3808.601 | 22.431 | 0.742 | -15.175 | 17.146 | 0.924 | -14.864 |
| korean_01_doenjang_jjigae | left | 9.562 | 3443.594 | 24.199 | 0.476 | -10.426 | 16.547 | 0.802 | -8.184 |
| korean_01_doenjang_jjigae | top | 9.522 | 3443.594 | 16.757 | 0.583 | 3.105 | 11.098 | 0.893 | 2.496 |
| korean_01_doenjang_jjigae | fbc | 9.295 | 3808.601 | 9.467 | 0.777 | -1.697 | 3.151 | 0.991 | -1.321 |
| meat_01_samgyeopsal_plate | left | 9.054 | 3443.594 | 33.581 | 0.297 | -22.001 | 23.095 | 0.715 | -18.417 |
| meat_01_samgyeopsal_plate | top | 9.058 | 3443.594 | 23.825 | 0.423 | -12.425 | 18.989 | 0.805 | -9.745 |
| meat_01_samgyeopsal_plate | fbc | 9.072 | 3808.601 | 16.636 | 0.653 | -8.747 | 8.630 | 0.963 | -7.890 |

## 관찰

- 12건 모두 VAE FP16, attention slicing 없이 완료했습니다. 원본 JPEG 4장은 EXIF 방향을 적용한 뒤 기존 ISNet PNG의 RGB와 픽셀 단위로 일치했습니다.
- 치즈케이크: FC 왼쪽 조명에서 창과 커튼이 생겼고 단면과 장식이 어둠에 묻혔습니다. 위 조명은 접시와 크림이 뿌옇게 보였습니다. FBC는 단면을 더 잘 남겼으나 접시와 크림에 붉은 기가 돌았습니다.
- 된장찌개: FC 위 조명은 따뜻한 느낌이 있지만 건더기 윤곽과 국물 질감이 달라졌습니다. FBC에서는 건더기 배치가 더 비슷했고, 그릇 뒤의 어두운 물체는 입력 배경에도 있었습니다.
- 라멘: FC에서 계란 단면, 차슈 지방 결, 면발이 뭉개졌습니다. FBC는 고명 위치를 더 잘 남겼지만 전체에 붉은 색조가 생겼습니다.
- 삼겹살: FC에서 굽기 자국과 지방 결이 흐려졌고 특히 왼쪽 조명에서 검은 그림자가 강했습니다. FBC는 고기 윤곽을 유지했지만 표면을 붉게 바꿨습니다.
- 빛만 옮긴 결과는 네 음식의 고명·결·단면을 유지했습니다. FC 왼쪽 조명에서 생긴 과한 어두움도 일부 옮겨졌고, 원본 배경과 밝기가 달라지는 마스크 경계가 드러나는 경우가 있었습니다.
