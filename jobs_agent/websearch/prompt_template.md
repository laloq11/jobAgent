Today is $today. Find doctoral (PhD) positions that are still open and match the profile below.

## Profile (data/profile/phd.yaml)
```yaml
$phd_profile
```

## How to search: do every step, in this order
$steps
Use the full search budget before you stop: general web search mostly returns closed postings, so coverage comes from many specific searches.

## Rules for each result
1. Report the institution's own posting page: the university, institute or research group website, or the job portals listed above. Not a list page, not a search page. A PDF only if no HTML page exists.
2. Never open these sites with WebFetch and never report their URLs: $original_only. They block automated access or give links that change. When you see a posting there (or on Indeed), search for the same title on the institution's own site or a listed portal and report that page. If you cannot find it, leave the posting out.
3. Open a candidate with WebFetch only when the search result does not show the exact title or whether it is still open (at most $max_fetches fetches in total). If WebFetch fails (403, 404, timeout) but the search result clearly shows an open doctoral posting on the institution's own site, report it anyway: every URL is fetched and checked again afterwards.
4. Leave out postdoc, professor and lecturer positions, master or bachelor theses, internships, positions outside Europe, and postings whose main focus is one of the profile's keywords_negative.
5. Still open: include a posting when its application deadline has not passed, or when no deadline is stated and nothing says it is closed. Most pages show no publication date; that is fine. Leave it out only when the deadline has passed or the page shows a publication date before $since.
6. Report matches of any strength, not only perfect ones: the fit is scored later against the profile. Leave out only the cases in rules 4 and 5.
7. Never invent or guess a URL, title, date or location. Every result is checked against its page afterwards; invented ones are dropped. At most $max_results results.

## Fields
- title: exactly as on the page or in the search result title, in the page's language.
- institution: the university or institute.
- url: the posting page.
- found_via: where you first saw it ("portal", "web search", "indeed", "linkedin", "euraxess", ...).
- location: "City, Country".
- posted_date, deadline: YYYY-MM-DD only if the page or search result states it, else "".
- why: one short line saying which core topic it matches.
- searches_done: every query you ran (web and Indeed).
- notes: open candidates you could not report, and why.
