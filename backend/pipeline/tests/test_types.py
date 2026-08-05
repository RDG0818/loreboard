from backend.pipeline.types import Candidate


def test_candidate_holds_expected_fields():
    c = Candidate(
        local_path="/tmp/foo.jpg",
        source="reddit",
        source_title="A cool painting",
        source_url="https://reddit.com/r/x/y",
    )
    assert c.local_path == "/tmp/foo.jpg"
    assert c.source == "reddit"
    assert c.source_title == "A cool painting"
    assert c.source_url == "https://reddit.com/r/x/y"
