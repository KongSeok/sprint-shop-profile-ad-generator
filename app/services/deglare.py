"""Opt-in highlight reduction for cutout previews."""

import numpy as np

def soften_highlights(rgba, knee=0.78, strength=0.6):
    """Whole-cutout highlight roll-off (like a phone's 'highlights -' slider). Opt-in by the owner."""
    a = rgba.astype(np.float32) / 255
    rgb = a[..., :3]; L = rgb.max(-1)
    over = np.clip((L - knee) / (1 - knee), 0, 1)
    target = L - strength * (1 - knee) * over ** 1.6
    f = np.where(L > 1e-3, target / np.maximum(L, 1e-3), 1)
    return (np.clip(np.dstack([rgb * f[..., None], a[..., 3]]), 0, 1) * 255).astype(np.uint8)

def blown_ratio(rgba):
    a = rgba.astype(np.float32) / 255; fg = a[..., 3] > 0.5
    mx = a[..., :3].max(-1); mn = a[..., :3].min(-1)
    return float(((mx > 0.97) & (mx - mn < 0.06) & fg).sum() / max(fg.sum(), 1))
