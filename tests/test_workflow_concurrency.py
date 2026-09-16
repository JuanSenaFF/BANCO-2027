import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "update-vagas.yml"


class WorkflowConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_runs_are_queued_instead_of_cancelling_each_other(self):
        self.assertIn("cancel-in-progress: false", self.workflow)
        self.assertNotIn("cancel-in-progress: true", self.workflow)

    def test_checkout_uses_latest_main_when_queued_run_starts(self):
        self.assertIn("fetch-depth: 0", self.workflow)
        self.assertIn("ref: main", self.workflow)

    def test_generated_catalog_is_not_rebased_over_concurrent_changes(self):
        self.assertNotIn("git pull --rebase", self.workflow)
        self.assertIn("git fetch origin main", self.workflow)
        self.assertIn('git rev-parse HEAD^', self.workflow)
        self.assertIn('git rev-parse origin/main', self.workflow)
        self.assertIn("git push origin HEAD:main", self.workflow)


if __name__ == "__main__":
    unittest.main()
