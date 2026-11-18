"""End-to-end smoke test for the Notion repo.

Run:  python3 -m jobs_agent.scripts.smoke_notion
Requires NOTION_TOKEN and NOTION_DB_ID in .env.
"""
from datetime import date
from jobs_agent.core.models import JobPosting
from jobs_agent.core.notion_repo import NotionRepo

TEST_URL = "https://example.com/jobs/smoke-test-001"


def main() -> None:
    repo = NotionRepo()

    print(f"exists_by_url before insert: {repo.exists_by_url(TEST_URL)}")

    posting = JobPosting(
        role="Smoke Test Engineer",
        company="Fake GmbH",
        url=TEST_URL,
        source="manual",
        location="Berlin",
        deadline=date(2026, 8, 1),
        fit_score=42.0,
        summary="Test row inserted by smoke_notion.py — safe to delete.",
        status="needs_review",
        todo="delete me",
    )
    page_id = repo.insert(posting)
    print(f"inserted page_id: {page_id}")

    print(f"exists_by_url after insert: {repo.exists_by_url(TEST_URL)}")

    repo.update_status(page_id, "rejected")
    print("updated status -> rejected")

    rejected = repo.query_by_status("rejected")
    print(f"rows with status=rejected: {len(rejected)}")

    print("OK")


if __name__ == "__main__":
    main()
