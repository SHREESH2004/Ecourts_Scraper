import unittest

from data_service import _calculate_judge_conviction_analysis


class AutomaticConvictionAnalysisTests(unittest.TestCase):
    def test_rates_use_classified_criminal_appeals_against_conviction(self):
        rows = [
            {
                "case_id": "Crl.A. No.-1",
                "title": "ALPHA VS STATE OF A",
                "verdict": "Appeal dismissed",
            },
            {
                "case_id": "Crl.A. No.-2",
                "title": "BETA VS THE STATE OF B",
                "verdict": "Appeal allowed",
            },
            {
                "case_id": "Criminal Appeal No. 3",
                "title": "GAMMA V/S STATE OF C",
                "verdict": "Partly allowed",
            },
            {
                "case_id": "Crl.A. No.-4",
                "title": "DELTA VS STATE OF D",
                "verdict": "Acquitted",
            },
            {
                "case_id": "Crl.A. No.-5",
                "title": "EPSILON VS STATE OF E",
                "verdict": "Remanded",
            },
            {
                "case_id": "Crl.A. No.-6",
                "title": "STATE OF F VS ZETA",
                "verdict": "Appeal allowed",
            },
            {
                "case_id": "SLP(Crl) No.-7",
                "title": "ETA VS STATE OF G",
                "verdict": "Appeal dismissed",
            },
            {
                "case_id": "Crl.A. No.-8",
                "title": "THETA VS IOTA",
                "verdict": "Appeal dismissed",
            },
            {
                "case_id": "C.A. No.-9",
                "title": "KAPPA VS STATE OF H",
                "verdict": "Appeal dismissed",
            },
        ]

        result = _calculate_judge_conviction_analysis(rows)

        self.assertEqual(result["conviction_appeal_candidates"], 5)
        self.assertEqual(result["outcome_distribution"]["CONVICTION_UPHELD"], 1)
        self.assertEqual(result["outcome_distribution"]["CONVICTION_MODIFIED"], 1)
        self.assertEqual(result["outcome_distribution"]["CONVICTION_SET_ASIDE"], 2)
        self.assertEqual(result["conviction_affirmation_rate"]["numerator"], 1)
        self.assertEqual(result["conviction_affirmation_rate"]["denominator"], 4)
        self.assertEqual(result["conviction_affirmation_rate"]["rate"], 25.0)
        self.assertEqual(result["conviction_reversal_rate"]["numerator"], 2)
        self.assertEqual(result["conviction_reversal_rate"]["denominator"], 4)
        self.assertEqual(result["conviction_reversal_rate"]["rate"], 50.0)
        self.assertEqual(result["outcome_classification_coverage"]["numerator"], 4)
        self.assertEqual(result["outcome_classification_coverage"]["denominator"], 5)
        self.assertEqual(result["outcome_classification_coverage"]["rate"], 80.0)

    def test_empty_dataset_has_unavailable_rates(self):
        result = _calculate_judge_conviction_analysis([])

        self.assertIsNone(result["conviction_affirmation_rate"]["rate"])
        self.assertIsNone(result["conviction_reversal_rate"]["rate"])
        self.assertIsNone(result["outcome_classification_coverage"]["rate"])


if __name__ == "__main__":
    unittest.main()
