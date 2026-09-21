import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from requirements_normalizer import (
    SCHEMA_VERSION,
    normalize_job_requirements,
    normalize_requirement,
    normalization_summary,
    validate_requirements,
)
from sync_database import requirement_rows


class RequirementsNormalizerTests(unittest.TestCase):
    def test_spring_boot_is_not_collapsed_into_java(self):
        spring = normalize_requirement("Spring Boot intermediário", True)
        java = normalize_requirement("Java intermediário", True)
        self.assertEqual(spring["skill"], "Java")
        self.assertEqual(spring["subskill"], "Spring Boot")
        self.assertEqual(spring["profileSkillIds"], ["spring"])
        self.assertEqual(java["profileSkillIds"], ["java"])

    def test_level_and_minimum_experience_are_explicit(self):
        requirement = normalize_requirement("Experiência de 2 anos com Python intermediário", True)
        self.assertEqual(requirement["category"], "technical")
        self.assertEqual(requirement["level"], 2)
        self.assertEqual(requirement["levelLabel"], "intermediário")
        self.assertEqual(requirement["minYears"], 2.0)

    def test_mandatory_differential_and_eliminatory_are_distinct(self):
        mandatory = normalize_requirement("Python", True)
        differential = normalize_requirement("AWS", False)
        eliminatory = normalize_requirement("Ensino superior completo", True)
        self.assertEqual(mandatory["requirementType"], "mandatory")
        self.assertEqual(differential["requirementType"], "differential")
        self.assertEqual(eliminatory["requirementType"], "eliminatory")
        self.assertEqual(eliminatory["category"], "education")

    def test_information_and_transformation_are_not_academic_education(self):
        cases = [
            ("Segurança da informação", "technical", "mandatory"),
            ("Extração, transformação e manipulação de dados com SQL", "technical", "mandatory"),
            ("Experiência em ambientes ágeis e transformação digital", "experience", "mandatory"),
            ("Organização, autonomia e interesse por governança de informação", "behavioral", "mandatory"),
        ]
        for text, category, requirement_type in cases:
            with self.subTest(text=text):
                normalized = normalize_requirement(text, True)
                self.assertEqual(normalized["category"], category)
                self.assertEqual(normalized["requirementType"], requirement_type)

    def test_complete_academic_terms_remain_education_gates(self):
        for text in [
            "Formação superior completa em Tecnologia da Informação",
            "Graduação em curso em Engenharia de Software",
            "Ensino superior completo",
            "Bacharelado em Ciência da Computação",
            "Bachelor degree in Computer Science",
        ]:
            with self.subTest(text=text):
                normalized = normalize_requirement(text, True)
                self.assertEqual(normalized["category"], "education")
                self.assertEqual(normalized["requirementType"], "eliminatory")

    def test_alternatives_and_transferable_skills_are_preserved(self):
        alternative = normalize_requirement("Java ou Go", True)
        transferable = normalize_requirement("Git e testes automatizados", True)
        self.assertEqual(alternative["relation"], "any")
        self.assertEqual({item["skill"] for item in alternative["skills"]}, {"Java", "Go"})
        self.assertEqual(alternative["unmappedSkillCount"], 1)
        self.assertTrue(transferable["transferable"])

    def test_affirmative_title_creates_an_eliminatory_gate(self):
        records = normalize_job_requirements({
            "role": "Desenvolvedor Júnior — vaga afirmativa PCD",
            "requirements": ["Python", "SQL", "Git"],
            "differentials": [],
        })
        eligibility = [record for record in records if record["category"] == "eligibility"]
        self.assertEqual(len(eligibility), 1)
        self.assertEqual(eligibility[0]["requirementType"], "eliminatory")
        self.assertEqual(eligibility[0]["source"], "title")

    def test_summary_and_database_rows_use_schema_v2(self):
        job = {
            "key": "job:1",
            "role": "Data Analyst I",
            "requirements": ["Python", "Ensino superior completo"],
            "differentials": ["AWS"],
        }
        job["requirementsStructured"] = normalize_job_requirements(job)
        summary = normalization_summary([job])
        rows = requirement_rows([job])
        self.assertEqual(summary["schemaVersion"], SCHEMA_VERSION)
        self.assertEqual(summary["eliminatory"], 1)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["category"], "technical")
        self.assertEqual(rows[0]["attributes"]["profileSkillIds"], ["python"])

    def test_invalid_contract_is_rejected_before_publish(self):
        with self.assertRaises(ValueError):
            validate_requirements([{
                "text": "Python",
                "mandatory": False,
                "requirementType": "mandatory",
                "category": "technical",
                "relation": "single",
                "level": 2,
                "minYears": None,
                "profileSkillIds": ["python"],
                "unmappedSkillCount": 0,
            }])


if __name__ == "__main__":
    unittest.main()
