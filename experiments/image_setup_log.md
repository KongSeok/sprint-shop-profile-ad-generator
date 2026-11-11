# 이미지 환경 설치 기록 · 2026-11-06

- 작업 폴더는 `sprint-image`, 브랜치는 `feat/image`. 별도 `.venv`에 Python 3.12.14 64비트 환경을 구성했다.
- 드라이버 621.01, NVIDIA GeForce RTX 2080 SUPER, VRAM 8192 MiB. `nvidia-smi`는 CUDA UMD 13.5를 표시했다. PyTorch 2.11.0과 torchvision 0.26.0은 공식 cu128 인덱스에서 설치했다.
- 일반 샌드박스 실행에서 세 호스트와 Playwright CDN 모두 `curl: (6) Could not resolve host`였다. 네트워크 제한 밖에서 pypi.org, download.pytorch.org, huggingface.co는 HTTP 200, cdn.playwright.dev 루트는 HTTP 400을 반환했다. DNS 실패는 제한된 실행 환경에서만 재현됐다.
- 이전 렌더 코드는 `app/services/renderer.py`에서 `RENDER_BROWSER_EXECUTABLE`로 브라우저 실행 파일을 지정했다. 현재는 Chromium 먼저 실행 후 실행 파일 누락 오류일 때 `channel="msedge"`로 시도한다. 기본 패키지 환경에서 실제 PNG 렌더링 테스트를 포함해 240개 테스트가 통과했다. 첫 pytest 실행의 `WinError 3`은 `--basetemp`의 부모 폴더 누락이 원인이었으며 `.pytest_cache` 생성 후 해결했다.
- ONNX Runtime GPU 1.31.1은 CUDA 세션에서 `cublasLt64_13.dll is missing (Error 126)`을 보고하고 CPU로 내려갔다. CUDA 12.8·cuDNN 9 조합인 1.26.0으로 고정한 뒤, `torch`를 먼저 import하고 소형 ONNX Add 그래프를 실행했다. 프로파일에서 Add 커널의 `CUDAExecutionProvider` 실행을 확인했다. 최종 사용 패키지는 `onnxruntime-gpu`다.
- 기본 앱 패키지와 이미지 패키지 설치 후 `pip check`는 `No broken requirements found.`를 반환했다.

```text
Python: 3.12.14
torch: 2.11.0+cu128
torch CUDA build: 12.8
CUDA available: True
GPU: NVIDIA GeForce RTX 2080 SUPER
Total VRAM: 8.00 GiB
CUDA tensor check: OK
onnxruntime: 1.26.0
ONNX Runtime providers: ['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider']
```

`diffusers.StableDiffusionPipeline`, transformers, accelerate, safetensors, rembg,
torchvision을 import했다. Windows용 bitsandbytes 0.50.2 설치와 CUDA
`Linear8bitLt` 소형 연산도 통과했다. import 중 Windows 분산 리디렉션 및
Triton FLOP 카운팅 안내가 나왔으나 확인한 CUDA 연산은 성공했다.
이 단계에서는 패키지와 GPU 연산까지 확인했다.
