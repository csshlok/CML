import unittest
from unittest.mock import patch

from backend.app.core.adaptive_scheduler import (
    capability_fingerprint,
    lane_limit,
    record_lane_observation,
    resource_budget,
    source_import_worker_count,
)


class AdaptiveSchedulerTests(unittest.TestCase):
    def test_unknown_hardware_remains_bounded(self) -> None:
        budget = resource_budget({"cpu_count": 64, "gpus": []})
        self.assertEqual(budget.cpu_workers, 8)
        self.assertEqual(budget.io_workers, 8)
        self.assertEqual(budget.local_model_slots, 1)

    def test_memory_pressure_reduces_parallel_work(self) -> None:
        budget = resource_budget(
            {
                "cpu_count": 32,
                "total_memory_bytes": 16 * 1024**3,
                "available_memory_bytes": 1024**3,
                "gpus": [{"vendor": "nvidia", "usable_vram_bytes": 16 * 1024**3}],
            }
        )
        self.assertEqual(budget.memory_pressure, "critical")
        self.assertEqual(budget.cpu_workers, 1)
        self.assertEqual(budget.io_workers, 1)
        self.assertEqual(budget.local_model_slots, 1)

    def test_large_gpu_can_offer_two_model_slots_without_affecting_small_batches(self) -> None:
        snapshot = {
            "cpu_count": 16,
            "total_memory_bytes": 32 * 1024**3,
            "available_memory_bytes": 24 * 1024**3,
            "gpus": [{"vendor": "nvidia", "usable_vram_bytes": 16 * 1024**3}],
        }
        self.assertEqual(resource_budget(snapshot).local_model_slots, 2)
        self.assertEqual(source_import_worker_count(3, snapshot), 3)

    def test_stable_window_grows_additively_and_pressure_reduces_only_that_lane(self) -> None:
        snapshot = {
            "cpu_count": 16,
            "total_memory_bytes": 32 * 1024**3,
            "available_memory_bytes": 24 * 1024**3,
            "gpus": [],
        }
        with (
            patch(
                "backend.app.core.adaptive_scheduler._load_lane_state",
                return_value={"current_limit": 3, "stable_observations": 2, "failure_count": 0},
            ),
            patch("backend.app.core.adaptive_scheduler._store_lane_state"),
        ):
            stable = record_lane_observation("extraction", success=True, snapshot=snapshot)
        self.assertEqual(stable["current_limit"], 4)
        self.assertEqual(stable["stable_observations"], 0)

        with (
            patch(
                "backend.app.core.adaptive_scheduler._load_lane_state",
                return_value={"current_limit": 4, "stable_observations": 2, "failure_count": 0},
            ),
            patch("backend.app.core.adaptive_scheduler._store_lane_state"),
        ):
            pressured = record_lane_observation(
                "extraction",
                success=False,
                pressure_event="database_lock",
                snapshot=snapshot,
            )
        self.assertEqual(pressured["current_limit"], 2)
        self.assertEqual(pressured["stable_observations"], 0)

    def test_chat_reservation_pauses_only_background_model_work(self) -> None:
        snapshot = {
            "cpu_count": 16,
            "total_memory_bytes": 32 * 1024**3,
            "available_memory_bytes": 24 * 1024**3,
            "gpus": [{"vendor": "generic", "usable_vram_bytes": 16 * 1024**3}],
        }
        with patch("backend.app.core.adaptive_scheduler._load_lane_state", return_value=None):
            self.assertEqual(
                lane_limit("local_model", snapshot, interactive_pending=True),
                0,
            )
            self.assertGreaterEqual(
                lane_limit("extraction", snapshot, interactive_pending=True),
                1,
            )

    def test_runtime_or_model_change_invalidates_learned_fingerprint(self) -> None:
        base = {"cpu_count": 8, "total_memory_bytes": 16 * 1024**3, "gpus": []}
        self.assertNotEqual(
            capability_fingerprint({**base, "model": "model-a"}),
            capability_fingerprint({**base, "model": "model-b"}),
        )


if __name__ == "__main__":
    unittest.main()
