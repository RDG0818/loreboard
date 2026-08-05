import dataclasses


@dataclasses.dataclass
class Candidate:
    local_path: str
    source: str  # "reddit" | "deviantart"
    source_title: str
    source_url: str
