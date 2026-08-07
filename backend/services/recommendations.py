import numpy as np


def compute_taste_vector(embeddings: list[list[float]]) -> list[float] | None:
    if not embeddings:
        return None
    return np.mean(np.array(embeddings), axis=0).tolist()
