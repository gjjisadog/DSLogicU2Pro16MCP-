import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from mcp_server.analysis import load_capture, measure_pwm


class AnalysisTests(unittest.TestCase):
    def test_pwm_measurement_and_path_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture = root / "capture-1"
            capture.mkdir()
            samples = np.array(([1] * 4 + [0] * 6) * 10, dtype="<u2")
            samples.tofile(capture / "capture.bin")
            (capture / "capture.json").write_text(
                json.dumps({"capture_id": "capture-1", "sample_rate_hz": 1_000_000}),
                encoding="utf-8",
            )

            result = measure_pwm("capture-1", channel=0, base_dir=str(root))
            self.assertTrue(result["ok"])
            self.assertEqual(result["cycle_count"], 8)
            self.assertAlmostEqual(result["frequency_hz"], 100_000, places=3)

            with self.assertRaises(ValueError):
                load_capture("..", base_dir=str(root))


if __name__ == "__main__":
    unittest.main()
