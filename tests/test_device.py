import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from proofparse.config import resolve_device


class DeviceTests(unittest.TestCase):
    def test_auto_uses_cuda_only_when_torch_can_use_it(self):
        for available, expected in ((True, "cuda"), (False, "cpu")):
            torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: available))
            with patch.dict(sys.modules, {"torch": torch}):
                self.assertEqual(resolve_device("auto"), expected)

    def test_missing_torch_falls_back_to_cpu(self):
        with patch.dict(sys.modules, {"torch": None}):
            self.assertEqual(resolve_device("auto"), "cpu")

    def test_manual_device_is_not_overridden(self):
        with patch.dict(sys.modules, {"torch": None}):
            self.assertEqual(resolve_device("cpu"), "cpu")
            self.assertEqual(resolve_device("cuda"), "cuda")

    def test_environment_override(self):
        with patch.dict("os.environ", {"PROOFPARSE_MINERU_DEVICE": "cpu"}):
            self.assertEqual(resolve_device(), "cpu")


if __name__ == "__main__": unittest.main()
