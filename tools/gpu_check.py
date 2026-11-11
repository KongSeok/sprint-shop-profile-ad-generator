"""Report image environment and verify a small CUDA tensor operation."""

import sys


def main() -> int:
    print(f"Python: {sys.version.split()[0]}")
    cuda_ok = False
    try:
        import torch

        print(f"torch: {torch.__version__}")
        print(f"torch CUDA build: {torch.version.cuda}")
        cuda_ok = torch.cuda.is_available()
        print(f"CUDA available: {cuda_ok}")
        if cuda_ok:
            gpu = torch.cuda.get_device_properties(0)
            print(f"GPU: {gpu.name}")
            print(f"Total VRAM: {gpu.total_memory / 1024**3:.2f} GiB")
            assert (torch.ones(4, device="cuda") + 1).sum().item() == 8
            print("CUDA tensor check: OK")
    except (ImportError, OSError, RuntimeError, AssertionError) as exc:
        cuda_ok = False
        print(f"PyTorch check failed: {exc}")

    try:
        import onnxruntime as ort

        print(f"onnxruntime: {ort.__version__}")
        print(f"ONNX Runtime providers: {ort.get_available_providers()}")
    except (ImportError, OSError) as exc:
        print(f"ONNX Runtime check failed: {exc}")
        return 1
    return 0 if cuda_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
