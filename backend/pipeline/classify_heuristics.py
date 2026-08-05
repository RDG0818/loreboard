import numpy as np
from PIL import Image, ImageFilter

MIN_WIDTH = 512
MIN_HEIGHT = 512
BLUR_VARIANCE_THRESHOLD = 100.0


def passes_resolution(path: str, min_width: int = MIN_WIDTH, min_height: int = MIN_HEIGHT) -> bool:
    with Image.open(path) as img:
        width, height = img.size
    return width >= min_width and height >= min_height


def blur_variance(path: str) -> float:
    """Higher variance in edge-detected pixels means a sharper image;
    a near-flat image (blurry, or a solid color) has low variance."""
    with Image.open(path) as img:
        gray = img.convert("L")
        edges = gray.filter(ImageFilter.FIND_EDGES)
        arr = np.asarray(edges, dtype=np.float64)
    return float(arr.var())


def passes_blur_check(path: str, threshold: float = BLUR_VARIANCE_THRESHOLD) -> bool:
    return blur_variance(path) >= threshold


def passes_heuristics(path: str) -> bool:
    return passes_resolution(path) and passes_blur_check(path)
