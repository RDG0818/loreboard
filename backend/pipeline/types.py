import dataclasses


@dataclasses.dataclass
class Candidate:
    local_path: str
    source: str  # "deviantart" | "artstation"
    source_title: str
    source_url: str
