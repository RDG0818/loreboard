import hashlib

from backend.pipeline import db
from backend.pipeline.types import Candidate


def hash_file(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def filter_new(conn, candidates: list[Candidate]) -> list[tuple[Candidate, str]]:
    """Returns (candidate, hash) pairs for candidates not already present
    in the images table. Also filters out candidates whose hash was already
    seen earlier in this same call (e.g. Reddit crossposts with identical
    content), so no two returned pairs share a hash."""
    result = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            image_hash = hash_file(candidate.local_path)
            if image_hash in seen:
                continue
            if not db.hash_exists(conn, image_hash):
                seen.add(image_hash)
                result.append((candidate, image_hash))
        except Exception as e:
            print(f"Dedupe: skipping candidate '{candidate.local_path}': {e}")
            continue
    return result
