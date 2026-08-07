from backend.services.recommendations import compute_taste_vector


def test_compute_taste_vector_returns_none_for_empty_list():
    assert compute_taste_vector([]) is None


def test_compute_taste_vector_averages_embeddings():
    result = compute_taste_vector([[1.0, 2.0], [3.0, 4.0]])
    assert result == [2.0, 3.0]


def test_compute_taste_vector_single_embedding_returns_itself():
    result = compute_taste_vector([[1.0, 2.0, 3.0]])
    assert result == [1.0, 2.0, 3.0]
