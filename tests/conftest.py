"""conftest.py — stub unavailable heavy dependencies for unit tests."""
import sys
from unittest.mock import MagicMock

openai_mock = MagicMock()
sys.modules.setdefault("openai", openai_mock)

anthropic_mock = MagicMock()
sys.modules.setdefault("anthropic", anthropic_mock)
