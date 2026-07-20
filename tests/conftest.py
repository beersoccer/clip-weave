"""conftest.py — stub unavailable heavy dependencies for unit tests."""
import sys
from unittest.mock import MagicMock

# Stub google.generativeai so videoagent.py can be imported without
# the real SDK installed in the test environment.
google_mock = MagicMock()
sys.modules.setdefault("google", google_mock)
sys.modules.setdefault("google.generativeai", google_mock.generativeai)
