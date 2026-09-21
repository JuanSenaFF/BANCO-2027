import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20260911004234_enforce_least_privilege.sql"
HARDENING_MIGRATION = ROOT / "supabase" / "migrations" / "20260912065130_harden_claim_refresh.sql"
PIPELINE_MIGRATION = ROOT / "supabase" / "migrations" / "20260916120000_add_job_candidate_pipeline.sql"
PIPELINE_HARDENING = ROOT / "supabase" / "migrations" / "20260916123000_harden_job_candidate_pipeline.sql"
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
        cls.hardening = HARDENING_MIGRATION.read_text(encoding="utf-8").lower()
        cls.pipeline = PIPELINE_MIGRATION.read_text(encoding="utf-8").lower()
        cls.pipeline_hardening = PIPELINE_HARDENING.read_text(encoding="utf-8").lower()
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

    def test_claim_refresh_keeps_elevated_code_out_of_public_schema(self):
        for sql in (self.hardening, self.schema):
            self.assertIn("function private.claim_refresh()", sql)
            self.assertIn("security definer", sql)
            self.assertIn("set search_path = ''", sql)
            self.assertIn("public.refresh_requests", sql)
            self.assertIn("function public.claim_refresh()", sql)
            self.assertIn("security invoker", sql)

    def test_claim_refresh_permissions_are_explicit(self):
        for sql in (self.hardening, self.schema):
            normalized = " ".join(sql.replace(",", " ").split())
            self.assertIn(
                "revoke all on function private.claim_refresh() from public anon authenticated",
                normalized,
            )
            self.assertIn(
                "grant execute on function private.claim_refresh() to authenticated",
                sql,
            )
            self.assertIn(
                "grant execute on function public.claim_refresh() to authenticated",
                sql,
            )

    def test_ingestion_payloads_are_backend_only(self):
        for table in ("source_registry", "job_candidates", "source_runs"):
            self.assertIn(f"alter table public.{table} enable row level security", self.pipeline)
            self.assertIn(
                f"revoke all privileges on table public.{table} from anon, authenticated",
                self.pipeline,
            )
            self.assertIn(
                f"grant select, insert, update, delete on table public.{table} to service_role",
                self.pipeline,
            )
        self.assertNotIn("create policy", self.pipeline)

    def test_candidate_terminal_state_cannot_regress_on_rediscovery(self):
        self.assertIn("private.preserve_candidate_terminal_state()", self.pipeline_hardening)
        self.assertIn("old.processing_status in ('published', 'closed')", self.pipeline_hardening)
        self.assertIn("new.processing_status := old.processing_status", self.pipeline_hardening)
        self.assertIn("job_candidates_published_job_idx", self.pipeline_hardening)


if __name__ == "__main__":
    unittest.main()
