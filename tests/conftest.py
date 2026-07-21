"""conftest.py — stub unavailable heavy dependencies for unit tests."""
import sys
from unittest.mock import MagicMock

# Stub openai so video_analyzer.py and html_generator.py can be imported
# without the real SDK installed in the test environment.
openai_mock = MagicMock()
sys.modules.setdefault("openai", openai_mock)
