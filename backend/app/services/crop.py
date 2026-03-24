"""Crop image by region (x, y, w, h) and save."""
from pathlib import Path
from PIL import Image


def crop_image(source_path: Path, x: int, y: int, width: int, height: int, output_path: Path) -> Path:
    img = Image.open(source_path).convert("RGB")
    box = (x, y, x + width, y + height)
    cropped = img.crop(box)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(output_path, "JPEG", quality=95)
    return output_path
