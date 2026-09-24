import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from market_model import classify, geography


def job(role, mandatory=(), differential=(), **extra):
    records = [
        {"category": "technical", "requirementType": "mandatory", "profileSkillIds": [skill]}
        for skill in mandatory
    ] + [
        {"category": "technical", "requirementType": "differential", "profileSkillIds": [skill]}
        for skill in differential
    ]
    return {
        "company": "Bradesco",
        "role": role,
        "location": "São Paulo, SP",
        "requirementsStructured": records,
        **extra,
    }


class MarketModelTests(unittest.TestCase):
    def test_data_role_is_target_and_reference_institution(self):
        result = classify(job("Cientista de Dados Júnior", ("python", "sql", "data")))
        self.assertEqual(result["marketSegment"], "core_technology")
        self.assertEqual(result["careerAlignment"], "target")
        self.assertEqual(result["careerWeight"], 1)
        self.assertEqual(result["institutionWeight"], 1.25)

    def test_finance_role_with_python_and_sql_is_target_market_segment(self):
        result = classify(job("Analista Jr de Risco de Crédito", ("python", "sql")))
        self.assertEqual(result["marketSegment"], "finance_with_technology")
        self.assertEqual(result["careerAlignment"], "target")

    def test_python_only_as_differential_stays_visible_as_context(self):
        result = classify(job("Analista Jr de Risco de Crédito", (), ("python",)))
        self.assertEqual(result["marketSegment"], "technology_differential")
        self.assertEqual(result["careerAlignment"], "context")
        self.assertEqual(result["careerWeight"], 0.15)

    def test_mandatory_automation_is_not_labeled_as_a_differential(self):
        result = classify(job("Analista Jr de Jornada Digital", ("auto", "data")))
        self.assertEqual(result["marketSegment"], "finance_with_technology")

    def test_java_only_role_does_not_steer_learning_plan(self):
        result = classify(job("Desenvolvedor Java Júnior", ("java", "spring")))
        self.assertEqual(result["marketSegment"], "core_technology")
        self.assertEqual(result["careerAlignment"], "other_stack")
        self.assertEqual(result["careerWeight"], 0)

    def test_other_location_is_market_context_only(self):
        result = classify(job("Analista de Dados Júnior", ("python", "data"), location="Recife, PE"))
        self.assertEqual(result["geographyScope"], "outside_scope")
        self.assertFalse(result["geographyEligible"])
        self.assertEqual(result["careerWeight"], 0)

    def test_linkedin_search_scope_is_kept_but_marked_unverified(self):
        result = geography({"searchScopeLocation": "São Paulo", "sourceProvider": "linkedin"})
        self.assertEqual(result["geographyScope"], "sao_paulo_unverified")
        self.assertEqual(result["geographyWeight"], 0.7)

    def test_remote_requires_brazil_evidence(self):
        brazil = geography({"location": "Brasil", "modality": "Remoto"})
        foreign = geography({"location": "Austin, United States", "modality": "Remoto"})
        unknown = geography({"location": "Remoto", "modality": "Remoto"})
        self.assertEqual(brazil["geographyScope"], "remote_brazil")
        self.assertEqual(foreign["geographyScope"], "outside_scope")
        self.assertFalse(foreign["geographyEligible"])
        self.assertEqual(unknown["geographyScope"], "remote_unverified")


if __name__ == "__main__":
    unittest.main()
