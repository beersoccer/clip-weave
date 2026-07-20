"""Shots output schema for clip-weave."""

from typing import Literal, Optional
from pydantic import BaseModel


class Shot(BaseModel):
    index: int
    start: float
    end: float
    duration: float
    type: Literal["hook", "product", "testimonial", "cta"]
    composition: str
    text_overlay: Optional[str] = None
    visual_element: str
    audio_cue: Optional[str] = None


class StyleInfo(BaseModel):
    pacing: Literal["fast", "medium", "slow"]
    color_tone: Literal["warm", "cool", "neutral"]
    typography: str
    transition: Literal["cut", "fade", "swipe", "zoom"]
    aspect_ratio: str


class ShotsOutput(BaseModel):
    style: StyleInfo
    shots: list[Shot]
    narrative_structure: Literal["AIDA", "PAS", "Hook-Story-Offer", "Before-After-Bridge"]
    total_duration: float
    shot_count: int
