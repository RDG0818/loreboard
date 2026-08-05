from PIL import Image
from sentence_transformers import SentenceTransformer
from sentence_transformers.util import cos_sim

REJECT_PROMPTS = [
    "A character reference sheet with multiple views of the same character.",
    "An orthographic character turnaround on a plain white background.",
    "A hand-drawn fantasy map or blueprint diagram.",
    "A black and white pencil sketch or line art drawing without color.",
    "A screenshot of a UI, inventory screen, or item chart.",
    "A photograph of a real person, a meme, or a comic book panel with text bubbles.",
]


def load_clip_model(model_name: str = "clip-ViT-L-14") -> SentenceTransformer:
    return SentenceTransformer(model_name)


def max_reject_similarity(model, image_path: str, reject_prompts: list[str] = REJECT_PROMPTS) -> float:
    """Scores the image against each reject prompt individually (not an
    averaged prototype) and returns the single highest similarity."""
    with Image.open(image_path) as img:
        if img.mode == "RGBA":
            img = img.convert("RGB")
        image_embedding = model.encode(img)
    prompt_embeddings = model.encode(reject_prompts)
    similarities = cos_sim(image_embedding, prompt_embeddings)[0]
    return float(similarities.max())


def passes_content_gate(model, image_path: str, threshold: float) -> bool:
    """Rejects the image if it scores too close to any single reject prompt."""
    return max_reject_similarity(model, image_path) < threshold
