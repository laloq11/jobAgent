"""Load profile config from YAML files."""
from pathlib import Path
import yaml

FILTER_PATH = Path("data/profile/filter.yaml")
COMPANIES_PATH = Path("data/profile/companies.yaml")
IGNORE_COMPANIES_PATH = Path("data/profile/ignore_companies.yaml")
SEARCHES_PATH = Path("data/profile/searches.yaml")


class FilterConfig:
    def __init__(self, allow: list[str], block: list[str]):
        self.allow = [t.lower() for t in allow]
        self.block = [t.lower() for t in block]


def load_filter(path: Path = FILTER_PATH) -> FilterConfig:
    if not path.exists():
        return FilterConfig([], [])
    data = yaml.safe_load(path.read_text()) or {}
    return FilterConfig(
        allow=data.get("allow", []) or [],
        block=data.get("block", []) or [],
    )


def load_ignored_companies(path: Path = IGNORE_COMPANIES_PATH) -> list[str]:
    """Hand-edited list of companies to ignore (`ignore:` in ignore_companies.yaml)."""
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    return [str(x) for x in (data.get("ignore") or []) if x]


def load_companies(path: Path = COMPANIES_PATH) -> dict:
    """Return raw dict from companies.yaml, coercing Nones to [] and ensuring 'allow'."""
    if not path.exists():
        return {"allow": [], "confirmed": [], "confirmed_ashby": []}
    data = yaml.safe_load(path.read_text()) or {}
    for k in list(data.keys()):
        if data[k] is None:
            data[k] = []
    data.setdefault("allow", [])
    data.setdefault("confirmed", [])
    data.setdefault("confirmed_ashby", [])
    return data


def update_section(section: str, items: list[str], path: Path = COMPANIES_PATH) -> None:
    """Rewrite one top-level list section, preserving everything else in the file."""
    lines = path.read_text().splitlines()
    n = len(lines)

    start = next(
        (i for i, ln in enumerate(lines) if ln.strip().rstrip(":") == section
         and ln.strip().endswith(":")),
        None,
    )
    new_body = [f"  - {x}" for x in sorted(set(items))]

    if start is None:
        result = lines[:]
        if result and result[-1].strip() != "":
            result.append("")
        result.append(f"{section}:")
        result.extend(new_body)
    else:
        # find end of this section: last indented/content line before next top-level key
        last_content = start
        end = n
        for j in range(start + 1, n):
            ln = lines[j]
            if ln.startswith((" ", "\t")):
                last_content = j
                continue
            if not ln.strip() or ln.strip().startswith("#"):
                continue
            end = last_content + 1
            break
        result = lines[: start + 1] + new_body + lines[end:]

    path.write_text("\n".join(result) + "\n")


def update_confirmed(new_confirmed: list[str], path: Path = COMPANIES_PATH) -> None:
    """Backward-compatible wrapper: writes the `confirmed:` section (greenhouse)."""
    update_section("confirmed", new_confirmed, path)

def load_searches(adapter: str, path: Path = SEARCHES_PATH) -> list[dict]:
    """Search parameter dicts for one adapter (`<adapter>:` in searches.yaml)."""
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    return [dict(s) for s in (data.get(adapter) or [])]
