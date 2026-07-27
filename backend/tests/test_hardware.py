from unittest import TestCase
from unittest.mock import patch

from backend.app.core import hardware


class HardwareDetectionTests(TestCase):
    def test_native_memory_fallback_is_used_when_psutil_fails(self) -> None:
        with (
            patch.dict("sys.modules", {"psutil": None}),
            patch.object(hardware, "_native_memory_status", return_value=(16_000, 8_000)),
        ):
            self.assertEqual(hardware._total_memory_bytes(), 16_000)
            self.assertEqual(hardware._available_memory_bytes(), 8_000)

    def test_nominal_sixteen_gb_device_is_not_downgraded(self) -> None:
        total_memory = int(15.1 * 1024**3)

        tier = hardware._hardware_tier(8, total_memory, True, [])

        self.assertEqual(tier, "cpu_high_spec")

    def test_dedicated_gpu_can_raise_hardware_tier(self) -> None:
        tier = hardware._hardware_tier(
            8,
            8 * 1024**3,
            True,
            [
                {
                    "usable_vram_bytes": 6 * 1024**3,
                    "shared_memory": False,
                }
            ],
        )

        self.assertEqual(tier, "gpu_or_high_spec_candidate")

    def test_shared_gpu_memory_does_not_raise_hardware_tier(self) -> None:
        tier = hardware._hardware_tier(
            4,
            8 * 1024**3,
            True,
            [
                {
                    "usable_vram_bytes": 8 * 1024**3,
                    "shared_memory": True,
                }
            ],
        )

        self.assertEqual(tier, "cpu_minimum_spec")

    def test_detection_failure_is_distinct_from_unsupported(self) -> None:
        with (
            patch.object(hardware, "_detect_avx2", return_value=(True, "test")),
            patch.object(hardware, "_detect_avx512", return_value=False),
            patch.object(hardware, "_total_memory_bytes", return_value=None),
            patch.object(hardware, "_available_memory_bytes", return_value=None),
            patch.object(hardware, "_detect_gpus", return_value=[]),
            patch.object(hardware, "_disk_free_bytes", return_value=1),
            patch.object(hardware.os, "cpu_count", return_value=8),
        ):
            status = hardware.hardware_status()

        self.assertEqual(status["hardware_tier"], "unknown")
        self.assertEqual(status["compatibility_detection"], "failed")
        self.assertEqual(status["detection_failures"], ["system_memory"])
        self.assertIn("system_memory", status["detail"])
