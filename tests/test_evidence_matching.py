"""Tests for evidence-linked job-fit assessment."""
import unittest

from evidence_matching import assess_evidence_linked_fit


class EvidenceLinkedFitTests(unittest.TestCase):
    def test_score_links_to_source_and_excerpt(self):
        result = assess_evidence_linked_fit({
            "evidence_records": [
                {"evidence_id": "ev-1", "source_url": "https://example.org/cv",
                 "excerpt": "Led a policy research project."},
                {"evidence_id": "ev-2", "source_url": "https://example.org/certificate",
                 "excerpt": "SQL certificate."},
            ],
            "requirement_evaluations": [
                {"criterion_id": "research", "criterion": "Research experience",
                 "score": 4, "weight": 3, "evidence_refs": ["ev-1"],
                 "rationale": "Led a directly relevant project."},
                {"criterion_id": "sql", "criterion": "SQL proficiency",
                 "score": 5, "weight": 1, "evidence_refs": ["ev-2"]},
            ],
        })
        self.assertEqual(result["status"], "EVIDENCE_LINKED")
        self.assertEqual(result["score"], 82.0)
        self.assertEqual(result["coverage"], 1.0)
        self.assertEqual(result["criterion_results"][0]["evidence_refs"], ["ev-1"])

    def test_missing_or_unresolvable_evidence_is_not_scored_as_zero(self):
        result = assess_evidence_linked_fit({
            "evidence_records": [
                {"evidence_id": "ev-no-excerpt", "source_url": "https://example.org/source",
                 "excerpt": ""}
            ],
            "requirement_evaluations": [
                {"criterion_id": "research", "criterion": "Research",
                 "score": 5, "weight": 2, "evidence_refs": ["missing", "ev-no-excerpt"]},
                {"criterion_id": "admin", "criterion": "Administration",
                 "score": 3, "weight": 2, "evidence_refs": []},
            ],
        })
        self.assertEqual(result["status"], "UNASSESSED")
        self.assertIsNone(result["score"])
        self.assertEqual(result["coverage"], 0.0)
        self.assertTrue(all(item["status"] == "UNSUPPORTED" for item in result["criterion_results"]))
        self.assertEqual(len(result["missing_evidence"]), 2)

    def test_partial_coverage_is_provisional_and_reports_counter_evidence(self):
        result = assess_evidence_linked_fit({
            "evidence_records": [
                {"evidence_id": "ev-1", "source_url": "https://example.org/a", "excerpt": "Relevant experience."},
                {"evidence_id": "ev-counter", "source_url": "https://example.org/b", "excerpt": "No experience in the required system."},
            ],
            "requirement_evaluations": [
                {"criterion_id": "experience", "score": 4, "weight": 1, "evidence_refs": ["ev-1"],
                 "counter_evidence_refs": ["ev-counter"]},
                {"criterion_id": "system", "score": 3, "weight": 1, "evidence_refs": []},
            ],
        })
        self.assertEqual(result["status"], "PROVISIONAL")
        self.assertEqual(result["coverage"], 0.5)
        self.assertEqual(result["score"], 80.0)
        self.assertEqual(result["counter_evidence"][0]["evidence_ref"], "ev-counter")

    def test_invalid_score_and_weight_are_rejected(self):
        result = assess_evidence_linked_fit({
            "evidence_records": [],
            "requirement_evaluations": [
                {"criterion_id": "bad", "score": 6, "weight": 0, "evidence_refs": ["x"]}
            ],
        })
        self.assertEqual(result["status"], "UNASSESSED")
        self.assertEqual(result["criterion_results"][0]["status"], "INVALID_SCORE_OR_WEIGHT")


if __name__ == "__main__":
    unittest.main()
