import unittest


class TrainingEvaluationContractTests(unittest.TestCase):
    def test_structural_readiness_helpers_are_explicitly_non_quality_gates(self) -> None:
        from backend.app.core.training_evaluation import (
            adapter_artifact_structural_readiness,
            cluster_dataset_structural_readiness_score,
            evaluate_adapter_quality,
            evaluate_cluster_dataset,
        )

        dataset = {
            "source_count": 10,
            "documents": [
                {"text": "x" * 6000, "summary": "summary " * 10},
                {"text": "y" * 6000, "summary": "summary " * 10},
            ],
        }

        structural_score = cluster_dataset_structural_readiness_score(dataset)
        legacy_score = evaluate_cluster_dataset(dataset)
        readiness = adapter_artifact_structural_readiness(
            dataset_structural_score=structural_score,
            adapter_dir_exists=True,
            adapter_valid=True,
            validation_count=4,
        )
        compatibility_report = evaluate_adapter_quality(
            dataset_score=structural_score,
            adapter_dir_exists=True,
            adapter_valid=True,
            validation_count=4,
        )

        self.assertEqual(structural_score, legacy_score)
        self.assertTrue(readiness["structural_readiness_only"])
        self.assertIn("must not be used as activation or release proof", readiness["detail"])
        self.assertEqual(compatibility_report["retrieval_only_score"], readiness["dataset_structural_score"])
        self.assertEqual(compatibility_report["adapter_score"], readiness["artifact_structural_score"])
        self.assertEqual(compatibility_report["quality_delta"], readiness["structural_delta"])


if __name__ == "__main__":
    unittest.main()
