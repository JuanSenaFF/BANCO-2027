import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20260911004234_enforce_least_privilege.sql"
SCHEMA = ROOT / "supabase" / "schema.sql"

CATALOG_TABLES = {
    "companies",
    "jobs",
    "job_requirements",
    "job_sources",
    "collection_meta",
    "market_snapshots",
}
PERSONAL_TABLES = {
    "user_state",
    "skills",
    "skill_history",
    "applications",
    "alerts",
    "profile_snapshots",
}


class SupabaseSecurityContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.migration = MIGRATION.read_text(encoding="utf-8").lower()
        cls.schema = SCHEMA.read_text(encoding="utf-8").lower()

    def test_migration_covers_every_application_table(self):
        for table in CATALOG_TABLES | PERSONAL_TABLES | {"refresh_requests"}:
            self.assertIn(f"public.{table}", self.migration)

    def test_browser_roles_are_reset_before_exact_grants(self):
        self.assertGreaterEqual(
            self.migration.count("revoke all privileges on table"), 3
        )
        self.assertIn("grant select on table", self.migration)
        self.assertIn("to anon, authenticated", self.migration)
        self.assertIn("grant select, insert, update, delete on table", self.migration)
        self.assertIn("to authenticated", self.migration)

    def test_future_objects_are_not_auto_exposed(self):
        for sql in (self.migration, self.schema):
            self.assertIn("alter default privileges for role postgres", sql)
            self.assertIn("revoke all privileges on tables from anon, authenticated", sql)
            self.assertIn("revoke execute on functions from public, anon, authenticated", sql)

    def test_schema_no_longer_leaves_non_dml_privileges_untouched(self):
        self.assertNotIn(
            "revoke insert, update, delete on public.%i from anon, authenticated",
            self.schema,
        )
        self.assertIn(
            "revoke all privileges on table public.%i from anon, authenticated",
            self.schema,
        )


if __name__ == "__main__":
    unittest.main()
