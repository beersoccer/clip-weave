"""Brand assets schema for clip-weave."""

from pathlib import Path
from typing import Optional
from pydantic import BaseModel


class BrandAssets(BaseModel):
    brand_name: str
    tagline: Optional[str] = None
    logo_path: Optional[Path] = None
    product_images: list[Path] = []
    color_palette: list[str] = []
    copy_points: list[str] = []
    target_aspect_ratio: str = "9:16"
