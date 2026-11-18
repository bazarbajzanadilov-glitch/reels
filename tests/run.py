"""Run offline verification; accidental provider calls fail before leaving this process."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from factory import http

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover(
        str(Path(__file__).parent), pattern="test_*.py"
    )
    with patch.object(
        http,
        "_open",
        side_effect=AssertionError("External provider calls are disabled in tests"),
    ):
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
