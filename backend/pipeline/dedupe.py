import hashlib

from backend.pipeline import db
from backend.pipeline.types import Candidate


def hash_file(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def filter_new(conn, candidates: list[Candidate]) -> list[tuple[Candidate, str]]:
    """Returns (candidate, hash) pairs for candidates not already present
    in the images table."""
    result = []
    for candidate in candidates:
        try:
            image_hash = hash_file(candidate.local_path)
            if not db.hash_exists(conn, image_hash):
                result.append((candidate, image_hash))
        except Exception as e:
            print(f"Dedupe: skipping candidate '{candidate.local_path}': {e}")
            continue
    return result
