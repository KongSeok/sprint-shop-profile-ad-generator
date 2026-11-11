"""Compute preview advice from the raw 8-bit alpha mask."""

from app.core.config import CUTOUT_MODEL as DEFAULT_CUTOUT_MODEL
from app.core.config import CUTOUT_POST_PROCESS_MASK as DEFAULT_POST_PROCESS_MASK

# 15장으로 정한 임시값. 초밥(0.32)과 라멘(0.30)은 반투명만으로 권장하지 않는다.
FOREGROUND_HINT_RATIO = 0.60
PARTIAL_HINT_RATIO = 0.50
FOREGROUND_MIN_ALPHA = 16
OPAQUE_MIN_ALPHA = 240


def suggest_original_preview(foreground_ratio: float, partial_foreground_ratio: float) -> bool:
    """Flag large or mostly translucent raw masks for a user preview."""
    return foreground_ratio >= FOREGROUND_HINT_RATIO or partial_foreground_ratio >= PARTIAL_HINT_RATIO


def analyze_mask(mask):
    if mask.mode != "L":
        raise ValueError("Expected an 8-bit grayscale alpha mask")
    histogram = mask.histogram()
    # Foreground: alpha 16–255 divided by all pixels.
    foreground = sum(histogram[FOREGROUND_MIN_ALPHA:])
    foreground_ratio = foreground / max(sum(histogram), 1)
    # Partial foreground: alpha 16–239 divided by foreground pixels (0 if empty).
    partial = sum(histogram[FOREGROUND_MIN_ALPHA:OPAQUE_MIN_ALPHA])
    partial_ratio = partial / max(foreground, 1)
    reason = None
    if not foreground:
        reason = "배경에서 음식 영역을 찾기 어려워요. 원본도 확인해 주세요."
    elif partial_ratio >= PARTIAL_HINT_RATIO:
        reason = "누끼에서 음식이 많이 비쳐 보여요. 원본도 확인해 주세요."
    elif foreground_ratio >= FOREGROUND_HINT_RATIO:
        reason = "음식이 화면을 꽉 채워서 배경 분리가 어려울 수 있어요."
    return {
        "suggest_original": reason is not None,
        "reason": reason,
        "foreground_ratio": foreground_ratio,
        "partial_foreground_ratio": partial_ratio,
    }
