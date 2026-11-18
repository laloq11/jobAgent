"""CEA thesis offers (https://www.theses-postdocs.cea.fr), HTML.

List: /Pages/Offre/ListeOffre.aspx?page=N&LCID=2057 (English view, 10 offers per
page). Paging loses the domain filter, so all pages are read. After the last
page the site wraps around to page 1, so paging stops at the first page that
brings no new reference (or at max_pages).

The detail page is fetched only for offers that pass the cheap check from
data/profile/cea.yaml (category or title keyword), to keep requests low.
The list date is the same for every offer (render date, not publication date),
so no published= is written; close_stale falls back to the 404 check.
"""
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable
import httpx
import yaml
from bs4 import BeautifulSoup
from jobs_agent.adapters._http import PoliteClient
from jobs_agent.core.models import JobPosting
from jobs_agent.core.logging import get_logger

log = get_logger("adapters.cea")

BASE = "https://www.theses-postdocs.cea.fr"
LIST_URL = f"{BASE}/Pages/Offre/ListeOffre.aspx"
LCID = "2057"  # English; 1036 = French
CONFIG_PATH = Path("data/profile/cea.yaml")
SUMMARY_MAX = 500

_REF = re.compile(r"\bSL-[A-Z]+-\d+-\d+\b")
# list link title: "Topic (Ref. : SL-DRF-27-0415) - Category"
_TITLE_ATTR = re.compile(r"\((?:Ref|Réf)\.?\s*:\s*(SL-[A-Z]+-\d+-\d+)\)\s*-\s*(.+)$")
# French labels, in case a detail page comes back in French
_FR_LABELS = {
    "Sujets de thèse": "Thesis topics",
    "Description de l'offre": "Job description",
    "Domaine": "Category",
    "Contrat": "Contract",
    "Université / école doctorale": "University / doctoral school",
    "Disponibilité du poste": "Position start date",
    "Personne à contacter par le candidat": "Person to be contacted by the applicant",
    "Tuteur / Responsable de thèse": "Tutor / Responsible thesis director",
    "Référence": "Reference",
}
_DESCRIPTION_FIELDS = [
    "Thesis topics", "Reference", "Category", "Contract", "Job description",
    "University / doctoral school", "Site", "Position start date",
    "Person to be contacted by the applicant", "Tutor / Responsible thesis director",
]


def load_config(path: Path = CONFIG_PATH) -> dict:
    data = (yaml.safe_load(path.read_text()) or {}) if path.exists() else {}
    return {
        "max_pages": int(data.get("max_pages") or 30),
        "categories": [str(c) for c in (data.get("categories") or [])],
        "title_keywords": [str(k) for k in (data.get("title_keywords") or [])],
    }


def parse_list(html: str) -> list[dict]:
    """Offers on one list page: title, href, ref, category."""
    soup = BeautifulSoup(html or "", "lxml")
    out = []
    for li in soup.select("li.ts-offer-list-item"):
        a = li.select_one("a.ts-offer-list-item__title-link")
        if a is None or not a.get("href"):
            continue
        m = _TITLE_ATTR.search(a.get("title") or "")
        ref = m.group(1) if m else ""
        if not ref:
            m_ref = _REF.search(li.get_text(" ", strip=True))
            ref = m_ref.group(0) if m_ref else ""
        out.append({
            "title": a.get_text(" ", strip=True),
            "href": a["href"],
            "ref": ref,
            "category": m.group(2).strip() if m else "",
        })
    return out


def parse_detail(html: str) -> dict[str, str]:
    """Detail page fields keyed by their (English) h2/h3 label."""
    soup = BeautifulSoup(html or "", "lxml")
    box = soup.select_one("#contenu-ficheoffre") or soup
    for t in box(["script", "style"]):
        t.decompose()
    labels = {h.get_text(" ", strip=True) for h in box.select("h2, h3")}
    fields: dict[str, list[str]] = {}
    current = None
    for line in box.get_text("\n", strip=True).splitlines():
        if line in labels:
            current = _FR_LABELS.get(line, line)
            fields.setdefault(current, [])
        elif current:
            fields[current].append(line)
    return {k: "\n".join(v).strip() for k, v in fields.items()}


def passes_title_check(item: dict, cfg: dict) -> bool:
    if item["category"].lower() in {c.lower() for c in cfg["categories"]}:
        return True
    title = item["title"].lower()
    return any(k.lower() in title for k in cfg["title_keywords"])


def detail_url(href: str) -> str:
    url = href if href.startswith("http") else BASE + href
    return url if "LCID=" in url else f"{url}{'&' if '?' in url else '?'}LCID={LCID}"


def _iso(ddmmyyyy: str) -> str:
    try:
        return datetime.strptime(ddmmyyyy.strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return ""


def to_posting(item: dict, fields: dict[str, str], url: str) -> JobPosting | None:
    try:
        topic = fields.get("Thesis topics") or item["title"]
        site = fields.get("Site", "").splitlines()[0] if fields.get("Site") else ""
        jd = fields.get("Job description", "")
        start = _iso(fields.get("Position start date", ""))
        description = "\n\n".join(
            f"{k}: {fields[k]}" for k in _DESCRIPTION_FIELDS if fields.get(k)
        )
        notes_bits = [
            f"id={item['ref']}" if item["ref"] else "",
            f"category={fields.get('Category') or item['category']}",
            f"start={start}" if start else "",
        ]
        return JobPosting(
            role=f"PhD thesis: {topic}",
            company="CEA",
            url=url,
            source="cea",
            location=f"{site}, France" if site else "France",
            summary=jd[:SUMMARY_MAX],
            description=description,
            notes=" | ".join(b for b in notes_bits if b),
            status="not_started",
        )
    except Exception as e:
        log.warning(f"skipping malformed offer ({e}): {url}")
        return None


class CeaAdapter:
    name = "cea"

    def __init__(self, config: dict | None = None, transport: httpx.BaseTransport | None = None,
                 min_interval: float = 1.0):
        self.cfg = config if config is not None else load_config()
        self.transport = transport
        self.min_interval = min_interval

    def fetch(self) -> Iterable[JobPosting]:
        offers: list[dict] = []
        refs: set[str] = set()
        with PoliteClient(min_interval=self.min_interval, transport=self.transport) as http:
            for page in range(1, self.cfg["max_pages"] + 1):
                try:
                    r = http.get(LIST_URL, params={"page": page, "LCID": LCID})
                except Exception as e:
                    log.exception(f"list page {page} failed: {e}")
                    break
                items = parse_list(r.text)
                new = [it for it in items if (it["ref"] or it["href"]) not in refs]
                log.info(f"  page {page}: {len(items)} offers, {len(new)} new")
                if not new:
                    break
                for it in new:
                    refs.add(it["ref"] or it["href"])
                offers.extend(new)
            else:
                log.warning(f"  stopped at max_pages={self.cfg['max_pages']}; raise it in {CONFIG_PATH}")

            candidates = [it for it in offers if passes_title_check(it, self.cfg)]
            log.info(f"  {len(offers)} offers, {len(candidates)} pass the title check")
            for it in candidates:
                url = detail_url(it["href"])
                try:
                    r = http.get(url)
                except Exception as e:
                    # skipped, not yielded: a posting without text would be filtered and marked seen
                    log.warning(f"  detail failed {it['ref']}: {e}")
                    continue
                p = to_posting(it, parse_detail(r.text), url)
                if p is not None:
                    yield p
