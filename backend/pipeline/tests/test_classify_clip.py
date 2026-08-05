from unittest.mock import MagicMock
import numpy as np
from PIL import Image
from backend.pipeline.classify_clip import max_reject_similarity, passes_content_gate


def _make_model(image_vec, prompt_vecs):
    model = MagicMock()

    def encode(x):
        if isinstance(x, list):
            return np.array(prompt_vecs)
        return np.array(image_vec)

    model.encode.side_effect = encode
    return model


def test_max_reject_similarity_returns_highest_single_prompt_score(tmp_path):
    path = tmp_path / "img.jpg"
    Image.new("RGB", (10, 10), color=(1, 2, 3)).save(path)

    # image vector is identical to the second reject prompt vector -> similarity 1.0 there
    image_vec = [1.0, 0.0]
    prompt_vecs = [[0.0, 1.0], [1.0, 0.0]]
    model = _make_model(image_vec, prompt_vecs)

    score = max_reject_similarity(model, str(path), reject_prompts=["a", "b"])

    assert score > 0.99


def test_passes_content_gate_rejects_high_similarity(tmp_path):
    path = tmp_path / "img.jpg"
    Image.new("RGB", (10, 10), color=(1, 2, 3)).save(path)

    image_vec = [1.0, 0.0]
    prompt_vecs = [[1.0, 0.0]]
    model = _make_model(image_vec, prompt_vecs)

    assert passes_content_gate(model, str(path), threshold=0.26) is False


def test_passes_content_gate_accepts_low_similarity(tmp_path):
    path = tmp_path / "img.jpg"
    Image.new("RGB", (10, 10), color=(1, 2, 3)).save(path)

    image_vec = [1.0, 0.0]
    prompt_vecs = [[0.0, 1.0]]
    model = _make_model(image_vec, prompt_vecs)

    assert passes_content_gate(model, str(path), threshold=0.26) is True
