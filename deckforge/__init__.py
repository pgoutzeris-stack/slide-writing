"""DeckForge — zero-dependency PowerPoint (PPTX) engine."""

__version__ = "1.0.0"

from .api import Deck
from .emu import Box, cm, emu_to_pt, hundredths_pt, inches, pt
from .errors import BuildError, DeckForgeError, PackageError, ParseError, SpecError
from .spec import build_from_spec, validate_spec
from .text import ParaFormat, RunFormat, TextFrame

__all__ = [
    "__version__",
    "Box",
    "BuildError",
    "Deck",
    "DeckForgeError",
    "PackageError",
    "ParaFormat",
    "ParseError",
    "RunFormat",
    "SpecError",
    "TextFrame",
    "build_from_spec",
    "cm",
    "emu_to_pt",
    "hundredths_pt",
    "inches",
    "pt",
    "validate_spec",
]
