"""Run digest: Notion rows touched in this run, sent via SMTP email.

Optionally prepends the run report Claude Code writes at the end of /jobs
(logs/run_report.md, overwritten every run), rendered from Markdown.
"""
import math
from datetime import date, datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
import re
import smtplib
import markdown
import yaml
from jobs_agent.core.config import settings
from jobs_agent.core.logging import get_logger
from jobs_agent.core.notion_repo import NotionRepo

log = get_logger("pipeline.notify")


def _prop_text(prop: dict) -> str:
    if not prop:
        return ""
    t = prop.get("type")
    if t == "title":
        return "".join(x.get("plain_text", "") for x in prop.get("title", []))
    if t == "rich_text":
        return "".join(x.get("plain_text", "") for x in prop.get("rich_text", []))
    if t == "select":
        s = prop.get("select")
        return s["name"] if s else ""
    if t == "url":
        return prop.get("url") or ""
    if t == "number":
        return str(prop.get("number") or "")
    return ""


def _row_summary(page: dict) -> dict:
    p = page.get("properties", {})
    return {
        "role": _prop_text(p.get("Role")),
        "company": _prop_text(p.get("Company")),
        "location": _prop_text(p.get("Location")),
        "url": _prop_text(p.get("url")),
        "source": _prop_text(p.get("Source")),
        "score": _prop_text(p.get("Fit Score")),
        "status": _prop_text(p.get("Status")),
        "cv_path": _prop_text(p.get("cv_path")),
        "cl_path": _prop_text(p.get("cover_letter_path")),
        "todo": _prop_text(p.get("todo")),
        "notion_url": page.get("url", ""),
    }


RUN_CONFIG_PATH = Path("data/profile/run.yaml")
FOLLOW_UP_DAYS = 14
OPEN_STATUSES = ["not_started", "approved_draft", "needs_review", "drafting",
                 "needs_final_review", "ready_to_submit", "submitted", "follow_up"]


def _date_start(prop: dict | None) -> date | None:
    d = (prop or {}).get("date") or {}
    try:
        return date.fromisoformat(d["start"][:10]) if d.get("start") else None
    except ValueError:
        return None


def pipeline_status(pages: list[dict], today: date | None = None) -> dict:
    """Counts over the whole Notion DB (not only this run) + rows with missing draft files.
    Draft paths are relative to the repo root (where /jobs runs)."""
    today = today or datetime.now(timezone.utc).date()
    count = {s: 0 for s in OPEN_STATUSES}
    unscored, overdue, missing = 0, 0, []
    for page in pages:
        p = page.get("properties", {})
        status = _prop_text(p.get("Status"))
        if status not in count:
            continue
        count[status] += 1
        if status == "not_started" and not _prop_text(p.get("Fit Score")):
            unscored += 1
        if status == "submitted" and not _prop_text(p.get("1st answer")):
            applied = _date_start(p.get("Application Date"))
            if applied and (today - applied).days >= FOLLOW_UP_DAYS:
                overdue += 1
        if status in ("needs_final_review", "ready_to_submit"):
            gone = [name for name, key in (("CV", "cv_path"), ("letter", "cover_letter_path"))
                    if not (_prop_text(p.get(key)) and Path(_prop_text(p.get(key))).exists())]
            if gone:
                missing.append(f"{_prop_text(p.get('Company'))} — {_prop_text(p.get('Role'))}: "
                               f"{' + '.join(gone)} missing")
    return {"count": count, "unscored": unscored, "overdue": overdue, "missing": missing}


def _run_limits(path: Path = RUN_CONFIG_PATH) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def status_markdown(st: dict, limits: dict) -> str:
    c = st["count"]
    per_score = limits.get("max_score_per_run") or 15
    per_draft = limits.get("max_drafts_per_run") or 5
    todos = [
        (c["needs_final_review"], "draft(s) to review → `needs_final_review` (README section 3)"),
        (c["needs_review"], "posting(s) to decide → `needs_review`: `approved_draft` or `low_fit`"),
        (c["drafting"], "failed draft(s) → `drafting`, reason in `todo`"),
        (c["ready_to_submit"], "application(s) to send → `ready_to_submit`, then `submitted`"),
        (st["overdue"], f"application(s) without answer for {FOLLOW_UP_DAYS}+ days → `follow_up`"),
    ]
    lines = ["## My todos (whole pipeline)", ""]
    lines += [f"- **{n}** {text}" for n, text in todos if n] or ["- nothing waiting on me"]
    lines += ["", "## Backlog", ""]
    lines.append(f"- **{st['unscored']}** unscored `not_started` row(s) → about "
                 f"**{math.ceil(st['unscored'] / per_score)}** more `/jobs` run(s) at "
                 f"{per_score} per run")
    lines.append(f"- **{c['approved_draft']}** `approved_draft` row(s) waiting for a draft → about "
                 f"**{math.ceil(c['approved_draft'] / per_draft)}** run(s) at {per_draft} per run")
    lines.append(f"- {c['submitted']} submitted, {c['follow_up']} in `follow_up`")
    if st["missing"]:
        lines += ["", "## Missing files", ""] + [f"- {m}" for m in st["missing"]]
    return "\n".join(lines) + "\n"


REPORT_PATH = Path("logs/run_report.md")
_TABLE_ATTRS = "border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse'"


def load_report(path: Path, since: str) -> str | None:
    """Report text, or None if missing or written before this run started."""
    if not path.exists():
        log.warning(f"report {path} not found; sending without it")
        return None
    started = datetime.fromisoformat(since.replace("Z", "+00:00"))
    written = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    if written < started:
        log.warning(f"report {path} is older than this run ({written:%Y-%m-%d %H:%M}Z); ignoring it")
        return None
    return path.read_text()


def report_html(report: str) -> str:
    # Python-Markdown needs a blank line between a paragraph and a list that follows it.
    report = re.sub(r"(?m)^(?![ \t]*(?:[-*+]|\d+\.)[ \t])([^\n|][^\n]*)\n([ \t]*(?:[-*+]|\d+\.)[ \t])",
                    r"\1\n\n\2", report)
    html = markdown.markdown(report, extensions=["tables"])
    return html.replace("<table>", f"<table {_TABLE_ATTRS}>")


def build_html(rows: list[dict], report: str | None = None, status: str | None = None) -> str:
    trs = []
    for r in rows:
        trs.append(
            f"<tr>"
            f"<td>{r['score']}</td>"
            f"<td>{r['status']}</td>"
            f"<td>{r['company']}</td>"
            f"<td>{r['role']}</td>"
            f"<td>{r['location']}</td>"
            f"<td>{r['source']}</td>"
            f"<td><a href='{r['url']}'>posting</a></td>"
            f"<td><a href='{r['notion_url']}'>notion</a></td>"
            f"<td>{r['cv_path']}<br>{r['cl_path']}</td>"
            f"<td>{r['todo']}</td>"
            f"</tr>"
        )
    head = report_html(report) + "<hr>" if report else ""
    head += report_html(status) + "<hr>" if status else ""
    return (
        "<html><body>"
        + head +
        f"<h3>{len(rows)} job(s) from this run</h3>"
        f"<table {_TABLE_ATTRS}>"
        "<thead><tr>"
        "<th>Score</th><th>Status</th><th>Company</th><th>Role</th><th>Location</th><th>Source</th>"
        "<th>Posting</th><th>Notion</th><th>Drafts</th><th>Todo</th>"
        "</tr></thead><tbody>"
        + "".join(trs) +
        "</tbody></table></body></html>"
    )


def build_text(rows: list[dict], report: str | None = None, status: str | None = None) -> str:
    lines = [report.rstrip(), "", "-" * 60, ""] if report else []
    lines += [status.rstrip(), "", "-" * 60, ""] if status else []
    lines += [f"{len(rows)} job(s) from this run", ""]
    for r in rows:
        lines.append(f"- [{r['score']}] {r['status']} | {r['company']} — {r['role']} "
                     f"({r['location']}, {r['source']})")
        if r["cv_path"] or r["cl_path"]:
            lines.append(f"    drafts:  {r['cv_path']}  {r['cl_path']}")
        if r["todo"]:
            lines.append(f"    todo:    {r['todo']}")
        lines.append(f"    posting: {r['url']}")
        lines.append(f"    notion:  {r['notion_url']}")
    return "\n".join(lines)


def send(subject: str, html: str, text: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["From"] = settings.notify_from or settings.smtp_user
    msg["To"] = settings.notify_to or settings.smtp_user
    msg["Subject"] = subject
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as s:
        s.starttls()
        s.login(settings.smtp_user, settings.smtp_password)
        s.send_message(msg)


DEFAULT_STATUSES = ["needs_final_review", "needs_review", "approved_draft", "drafting"]


def run_notify(since: str | None = None, statuses: list[str] | None = None,
               send_empty: bool = False, report_path: Path | None = None,
               preview: Path | None = None) -> None:
    """Email rows edited after `since` (ISO UTC; default: last 24h) with given statuses.

    report_path: Markdown run report to put on top (skipped if older than `since`).
    A report alone is enough to send, so quiet runs still leave a record.
    preview: write <preview>.html / <preview>.txt instead of sending.
    """
    if preview is None and (not settings.smtp_user or not settings.smtp_password):
        log.error("SMTP_USER/SMTP_PASSWORD missing; skipping")
        return

    statuses = statuses or DEFAULT_STATUSES
    if since is None:
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    log.info(f"querying rows edited since {since} with status in {statuses}")

    repo = NotionRepo()
    rows = [_row_summary(p) for p in repo.query_edited_since(since, statuses)]
    rows.sort(key=lambda r: float(r["score"] or 0), reverse=True)
    log.info(f"{len(rows)} rows to include")
    report = load_report(report_path, since) if report_path else None

    if not rows and not report and not send_empty:
        log.info("nothing to notify — skipping email")
        return

    st = pipeline_status(repo.query_by_statuses(OPEN_STATUSES))
    status = status_markdown(st, _run_limits())
    c = st["count"]
    subject = (f"[job-agent] {c['needs_final_review']} draft(s) to review · "
               f"{c['needs_review']} to decide · {st['unscored']} unscored left")
    html, text = build_html(rows, report, status), build_text(rows, report, status)
    if preview:
        preview.with_suffix(".html").write_text(html)
        preview.with_suffix(".txt").write_text(f"Subject: {subject}\n\n{text}")
        log.info(f"preview written to {preview.with_suffix('.html')} (not sent)")
        return
    send(subject, html, text)
    log.info("email sent")
