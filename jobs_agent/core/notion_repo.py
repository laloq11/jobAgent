"""Notion repo for the Job Pipeline database (API 2025-09-03+)."""
from typing import Optional
from notion_client import Client
from .config import settings
from .models import JobPosting, Status


# ---- property builders ----

def _title(text: str) -> dict:
    return {"title": [{"text": {"content": text}}]}


def _rich_text(text: str) -> dict:
    return {"rich_text": [{"text": {"content": text}}]} if text else {"rich_text": []}


def _select(name: Optional[str]) -> dict:
    return {"select": {"name": name} if name else None}


def _number(value: Optional[float]) -> dict:
    return {"number": value}


def _url(value: str) -> dict:
    return {"url": value}


def _date(value) -> dict:
    return {"date": {"start": value.isoformat()} if value else None}


# ---- repository ----

class NotionRepo:
    def __init__(self, token: str = None, db_id: str = None):
        self.client = Client(auth=token or settings.notion_token)
        self.db_id = db_id or settings.notion_db_id
        self.data_source_id = self._resolve_data_source_id()

    def _resolve_data_source_id(self) -> str:
        db = self.client.databases.retrieve(database_id=self.db_id)
        sources = db.get("data_sources", [])
        if not sources:
            raise RuntimeError(f"No data sources on database {self.db_id}")
        return sources[0]["id"]

    def _posting_to_props(self, p: JobPosting) -> dict:
        return {
            "Role": _title(p.role),
            "Company": _rich_text(p.company),
            "url": _url(str(p.url)),
            "Source": _select(p.source),
            "Location": _rich_text(p.location),
            "Deadline": _date(p.deadline),
            "Fit Score": _number(p.fit_score),
            "Summary": _rich_text(p.summary),
            "Status": _select(p.status),
            "cover_letter_path": _rich_text(p.cover_letter_path),
            "cv_path": _rich_text(p.cv_path),
            "todo": _rich_text(p.todo),
            "Application Date": _date(p.application_date),
            "1st interview": _date(p.first_interview),
            "1st answer": _select(p.first_answer),
            "Notes": _rich_text(p.notes),
        }

    def insert(self, posting: JobPosting) -> str:
        page = self.client.pages.create(
            parent={"data_source_id": self.data_source_id},
            properties=self._posting_to_props(posting),
        )
        return page["id"]

    def exists_by_url(self, url: str) -> bool:
        res = self.client.data_sources.query(
            data_source_id=self.data_source_id,
            filter={"property": "url", "url": {"equals": url}},
            page_size=1,
        )
        return len(res["results"]) > 0

    def update_status(self, page_id: str, status: Status) -> None:
        self.client.pages.update(
            page_id=page_id,
            properties={"Status": _select(status)},
        )

    def update_fields(self, page_id: str, **fields) -> None:
        """Update a subset of row fields. Keys: fit_score, summary, deadline,
        status, cv_path, cover_letter_path, todo."""
        builders = {
            "fit_score": ("Fit Score", _number),
            "summary": ("Summary", _rich_text),
            "deadline": ("Deadline", _date),
            "status": ("Status", _select),
            "cv_path": ("cv_path", _rich_text),
            "cover_letter_path": ("cover_letter_path", _rich_text),
            "todo": ("todo", _rich_text),
        }
        props = {}
        for key, value in fields.items():
            name, build = builders[key]
            props[name] = build(value)
        self.client.pages.update(page_id=page_id, properties=props)

    def _query_all(self, filter: dict, limit: Optional[int] = None,
                   sorts: Optional[list[dict]] = None) -> list[dict]:
        results: list[dict] = []
        start_cursor = None
        while True:
            kwargs = dict(data_source_id=self.data_source_id, filter=filter, page_size=100)
            if sorts:
                kwargs["sorts"] = sorts
            if start_cursor:
                kwargs["start_cursor"] = start_cursor
            res = self.client.data_sources.query(**kwargs)
            results.extend(res["results"])
            if limit and len(results) >= limit:
                return results[:limit]
            if not res.get("has_more"):
                return results
            start_cursor = res.get("next_cursor")

    def query_by_status(self, status: Status, limit: Optional[int] = None) -> list[dict]:
        return self._query_all({"property": "Status", "select": {"equals": status}}, limit)

    def query_to_draft(self, limit: Optional[int] = None) -> list[dict]:
        """approved_draft rows, highest Fit Score first (rows without a score last)."""
        return self._query_all(
            {"property": "Status", "select": {"equals": "approved_draft"}}, limit,
            sorts=[{"property": "Fit Score", "direction": "descending"}])

    def query_by_statuses(self, statuses: list[Status]) -> list[dict]:
        return self._query_all(
            {"or": [{"property": "Status", "select": {"equals": s}} for s in statuses]})

    def query_unscored(self, limit: Optional[int] = None) -> list[dict]:
        """not_started rows with empty Fit Score."""
        return self._query_all({"and": [
            {"property": "Status", "select": {"equals": "not_started"}},
            {"property": "Fit Score", "number": {"is_empty": True}},
        ]}, limit)

    def query_edited_since(self, iso_ts: str, statuses: list[Status]) -> list[dict]:
        """Rows edited after iso_ts whose status is in statuses."""
        return self._query_all({"and": [
            {"property": "Last edited time", "last_edited_time": {"after": iso_ts}},
            {"or": [{"property": "Status", "select": {"equals": s}} for s in statuses]},
        ]})

    def trash_page(self, page_id: str) -> None:
        self.client.pages.update(page_id=page_id, in_trash=True)
