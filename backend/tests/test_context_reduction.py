import unittest


class ContextReductionTests(unittest.TestCase):
    def test_salient_excerpt_prefers_query_relevant_segments(self) -> None:
        from backend.app.core.context_reduction import salient_excerpt

        text = (
            "General introduction that does not matter. "
            "The benchmark report shows a 64 percent token reduction for repeated context. "
            "Closing note."
        )

        excerpt = salient_excerpt(text, prompt="token reduction benchmark", token_budget=18)

        self.assertIn("token reduction", excerpt.lower())
        self.assertNotIn("General introduction", excerpt)

    def test_build_context_reduction_plan_dedupes_and_emits_diagnostics(self) -> None:
        from backend.app.core.context_reduction import build_context_reduction_plan

        citations = [
            {"source_id": "a", "source_title": "One", "snippet": "Benchmark packet latency and token reduction proof.", "score": 0.9},
            {"source_id": "a", "source_title": "One", "snippet": "Benchmark packet latency and token reduction proof.", "score": 0.8},
            {"source_id": "b", "source_title": "Two", "snippet": "Different source about ingestion timing and parser speed.", "score": 0.7},
        ]
        memory_items = [
            {"kind": "fact", "summary": "Users care about repeated-turn token savings and first-answer speed."},
            {"kind": "fact", "summary": "Less relevant archival note."},
        ]
        working_memory = {"summary": "Current benchmark focus is parser speed, token reduction, and retrieval proof."}

        plan = build_context_reduction_plan(
            prompt="benchmark token reduction and parser speed",
            citations=citations,
            recent_turns=[{"role": "user", "content": "remind me about parser speed"}],
            memory_items=memory_items,
            working_memory=working_memory,
            token_budget=120,
            cluster_descriptions=["Research benchmark work"],
        )

        self.assertLessEqual(len(plan["citations"]), 3)
        self.assertEqual(plan["diagnostics"]["raw_candidate_citation_count"], 3)
        self.assertGreaterEqual(plan["diagnostics"]["dropped_citation_count"], 1)
        self.assertIn("duplicate_evidence", {item["reason"] for item in plan["diagnostics"]["dropped_citations"]})
        self.assertIn("strategy", plan["diagnostics"])
        self.assertTrue(plan["memory_items"])


if __name__ == "__main__":
    unittest.main()
