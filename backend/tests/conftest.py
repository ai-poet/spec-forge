from __future__ import annotations

import os
import tempfile


TEST_DATA_DIR = tempfile.mkdtemp(prefix="specforge-tests-")
os.environ["SPECFORGE_DATA_DIR"] = TEST_DATA_DIR
os.environ["SPECFORGE_MODE"] = "dry-run"
