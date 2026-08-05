import numpy as np
from PIL import Image
from backend.pipeline.classify_heuristics import (
    passes_resolution,
    passes_blur_check,
    passes_heuristics,
)


def _write_image(path, size, arr=None):
    if arr is None:
        img = Image.new("RGB", size, color=(120, 120, 120))
    else:
        img = Image.fromarray(arr, mode="RGB")
    img.save(path)


def test_passes_resolution_rejects_small_image(tmp_path):
    path = tmp_path / "small.jpg"
    _write_image(path, (100, 100))
    assert passes_resolution(str(path)) is False


def test_passes_resolution_accepts_large_image(tmp_path):
    path = tmp_path / "large.jpg"
    _write_image(path, (800, 800))
    assert passes_resolution(str(path)) is True


def test_passes_blur_check_rejects_flat_color(tmp_path):
    path = tmp_path / "flat.jpg"
    _write_image(path, (600, 600))  # solid color: near-zero edge variance
    assert passes_blur_check(str(path)) is False


def test_passes_blur_check_accepts_noisy_image(tmp_path):
    path = tmp_path / "noisy.jpg"
    rng = np.random.default_rng(42)
    arr = rng.integers(0, 255, size=(600, 600, 3), dtype=np.uint8)
    _write_image(path, (600, 600), arr=arr)
    assert passes_blur_check(str(path)) is True


def test_passes_heuristics_requires_both_checks(tmp_path):
    path = tmp_path / "small_flat.jpg"
    _write_image(path, (100, 100))
    assert passes_heuristics(str(path)) is False
