"""Regression tests for the self-contained query planner port."""
import unittest

from search_engine import (
    AdaptiveSearchPlanner,
    CandidateEvidence,
    SearchMatrixPlanner,
    SearchCombination,
)


class SearchEngineTests(unittest.TestCase):
    def test_query_ids_are_stable(self):
        a = SearchCombination("교육정책", "대학", "교육정책 대학 전국", 1)
        b = SearchCombination("교육정책", "대학", "교육정책 대학 전국", 99)
        self.assertEqual(a.combination_id, b.combination_id)

    def test_planner_emits_unique_bounded_queries(self):
        planner = AdaptiveSearchPlanner(SearchMatrixPlanner())
        plans = planner.plan(CandidateEvidence(("교육행정", "정책연구")), "현재 채용", limit=40)
        queries = [p.combination.query for p in plans]
        self.assertGreater(len(queries), 0)
        self.assertLessEqual(len(queries), 40)
        self.assertEqual(len(queries), len(set(queries)))
        self.assertTrue(all("현재 채용" in query for query in queries))

    def test_unknown_outcomes_remain_exploration(self):
        planner = AdaptiveSearchPlanner(SearchMatrixPlanner(), outcome_memory={})
        plans = planner.plan(CandidateEvidence(("교육행정",)), limit=5)
        self.assertTrue(all(plan.exploration for plan in plans))

    def test_known_outcome_is_used_without_fabricating_history(self):
        base = SearchMatrixPlanner().derive(CandidateEvidence(("교육행정",)), limit=2)
        memory = {base[0].combination_id: 0.9}
        plans = AdaptiveSearchPlanner(SearchMatrixPlanner(), outcome_memory=memory).plan(
            CandidateEvidence(("교육행정",)), limit=2
        )
        matched = [p for p in plans if p.combination.combination_id in memory]
        self.assertTrue(matched)
        self.assertEqual(matched[0].prior_utility, 0.9)
        self.assertFalse(matched[0].exploration)


if __name__ == "__main__":
    unittest.main()
