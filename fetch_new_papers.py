#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "bibtexparser>=1.4,<2",
#   "requests>=2.31",
# ]
# ///
"""
Fetch new papers from Semantic Scholar and produce a draft BibTeX file.

Usage:
    uv run fetch_new_papers.py

The script compares papers returned by the Semantic Scholar author API against
all entries in papers.bib, workshops.bib, and preprints.bib (matching on DOI,
arXiv ID, or title). Record the arXiv version of a published or workshop paper
via `authoritative_link` so it is recognised even when titles differ. New papers are
written to new_papers_draft.bib with placeholder custom fields for manual review.

Configuration: set SEMANTIC_SCHOLAR_AUTHOR_ID below, or find your ID at
https://www.semanticscholar.org by searching your name — the URL contains a
numeric ID like /author/Austin-Tripp/2145663280.
"""

import re
import sys
import time
import unicodedata
from pathlib import Path

import bibtexparser
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Semantic Scholar sometimes splits one person into several author profiles, so
# list every ID that belongs to you. Results are merged and deduplicated.
SEMANTIC_SCHOLAR_AUTHOR_IDS = [
    "115766771",
    "2264318847",  # second profile holding recent papers (merge requested)
]
REPO_DIR = Path(__file__).parent
BIB_FILES = ["papers.bib", "workshops.bib", "preprints.bib"]
OUTPUT_FILE = REPO_DIR / "new_papers_draft.bib"
SS_API_BASE = "https://api.semanticscholar.org/graph/v1"
CROSSREF_BASE = "https://api.crossref.org/works"

PLACEHOLDER_FIELDS = """\
  % ── Fill in the fields below ──────────────────────────────────────────────
  website_exclude = {REVIEW_NEEDED},  % true or false
  website_slug = {REVIEW_NEEDED},     % kebab-case slug, or remove if excluded
  keywords = {},                       % ownwork, workshop, preprint — or leave blank
  % ──────────────────────────────────────────────────────────────────────────"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Lowercase, strip accents, keep only alphanumerics for fuzzy matching."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", text.lower())


# Matches new-style (2406.07709) and old-style (hep-th/9901001) arXiv IDs when they
# appear as "arXiv:ID", in an arxiv.org URL, or in an arXiv DOI (10.48550/arXiv.ID).
_ARXIV_ID_RE = re.compile(
    r"(?:arxiv[:./]|arxiv\.org/(?:abs|pdf)/)\s*"
    r"(\d{4}\.\d{4,5}|[a-z\-]+(?:\.[a-z]{2})?/\d{7})(?:v\d+)?",
    re.IGNORECASE,
)
# Fields that may carry an arXiv reference (e.g. journal={arXiv preprint arXiv:...},
# or authoritative_link pointing at the arXiv version of a published paper).
_ARXIV_FIELDS = ("journal", "eprint", "url", "authoritative_link", "doi", "note", "pdf")


def _arxiv_ids_in(entry: dict) -> set[str]:
    """Return normalized (lowercase, version-stripped) arXiv IDs referenced by an entry."""
    ids: set[str] = set()
    for field in _ARXIV_FIELDS:
        ids.update(m.lower() for m in _ARXIV_ID_RE.findall(entry.get(field, "")))
    return ids


def load_existing_keys(bib_files: list[Path]) -> tuple[set[str], set[str], set[str]]:
    """Return (normalized DOIs, normalized titles, arXiv IDs) from existing bib files."""
    dois: set[str] = set()
    titles: set[str] = set()
    arxiv_ids: set[str] = set()
    for path in bib_files:
        if not path.exists():
            continue
        with open(path) as f:
            lib = bibtexparser.load(f)
        for entry in lib.entries:
            if doi := entry.get("doi", "").strip():
                dois.add(_normalize(doi))
            if title := entry.get("title", "").strip():
                titles.add(_normalize(title))
            arxiv_ids |= _arxiv_ids_in(entry)
    return dois, titles, arxiv_ids


def _get(url: str, **kwargs) -> requests.Response:
    """GET with retry/backoff on Semantic Scholar rate limiting (HTTP 429)."""
    for attempt in range(6):
        resp = requests.get(url, timeout=15, **kwargs)
        if resp.status_code != 429:
            resp.raise_for_status()
            return resp
        wait = 2 ** attempt
        print(f"  Rate limited (429); retrying in {wait}s...")
        time.sleep(wait)
    resp.raise_for_status()
    return resp


def search_author(name: str) -> str | None:
    """Interactive: search Semantic Scholar for an author and return their ID."""
    resp = _get(
        f"{SS_API_BASE}/author/search",
        params={"query": name, "fields": "name,affiliations,paperCount"},
    )
    data = resp.json().get("data", [])
    if not data:
        print("No authors found.")
        return None
    print("\nAuthors found:")
    for i, a in enumerate(data[:5]):
        affil = "; ".join(a.get("affiliations", [])) or "no affiliation listed"
        print(f"  [{i}] {a['name']} — {a['paperCount']} papers — {affil} (ID: {a['authorId']})")
    choice = input("\nEnter number to select, or 'q' to quit: ").strip()
    if choice == "q":
        return None
    return data[int(choice)]["authorId"]


def fetch_author_papers(author_id: str) -> list[dict]:
    """Return all papers for the given Semantic Scholar author ID."""
    url = f"{SS_API_BASE}/author/{author_id}/papers"
    params = {
        "fields": "paperId,title,year,authors,externalIds,venue,publicationTypes",
        "limit": 100,
    }
    papers: list[dict] = []
    while True:
        body = _get(url, params=params).json()
        papers.extend(body.get("data", []))
        # The API pages with an integer offset; "next" is absent on the last page.
        if (next_offset := body.get("next")) is None:
            break
        params["offset"] = next_offset
    return papers


def fetch_papers_for_authors(author_ids: list[str]) -> list[dict]:
    """Fetch and merge papers across several author IDs, deduplicated by paperId."""
    merged: dict[str, dict] = {}
    for author_id in author_ids:
        papers = fetch_author_papers(author_id)
        print(f"  {author_id}: {len(papers)} papers")
        for paper in papers:
            merged.setdefault(paper.get("paperId") or paper.get("title", ""), paper)
    return list(merged.values())


def _is_arxiv_doi(doi: str) -> bool:
    return doi.startswith("10.48550/")


def get_bibtex_from_crossref(doi: str) -> str | None:
    """Fetch BibTeX for a DOI from CrossRef."""
    try:
        resp = requests.get(
            f"{CROSSREF_BASE}/{doi}/transform/application/x-bibtex",
            headers={"Accept": "application/x-bibtex"},
            timeout=15,
        )
        if resp.ok and resp.text.strip().startswith("@"):
            return resp.text.strip()
    except requests.RequestException:
        pass
    return None


def _make_cite_key(paper: dict) -> str:
    """Generate a cite key: firstauthorlastname + year + firsttitleword."""
    authors = paper.get("authors") or []
    if authors:
        # Semantic Scholar returns names as "Firstname Lastname"
        last = authors[0].get("name", "").split()[-1]
        last = re.sub(r"[^a-zA-Z]", "", last).lower()
    else:
        last = "unknown"
    year = paper.get("year") or "0000"
    title_words = re.split(r"\W+", paper.get("title", ""))
    first_word = re.sub(r"[^a-zA-Z]", "", (title_words[0] if title_words else "")).lower()
    return f"{last}{year}{first_word}"


def _format_authors(paper: dict) -> str:
    """Format author list in BibTeX 'Lastname, Firstname and ...' style."""
    authors = paper.get("authors") or []
    parts = []
    for a in authors:
        name = a.get("name", "").strip()
        # S2 returns "Firstname [MI.] Lastname" — convert to "Lastname, Firstname"
        tokens = name.split()
        if len(tokens) >= 2:
            parts.append(f"{tokens[-1]}, {' '.join(tokens[:-1])}")
        else:
            parts.append(name)
    return " and ".join(parts)


def build_bibtex_from_metadata(paper: dict) -> str:
    """Construct a BibTeX entry from S2 paper metadata fields."""
    ext = paper.get("externalIds") or {}
    doi = ext.get("DOI", "")
    arxiv = ext.get("ArXiv", "")
    year = paper.get("year") or ""
    title = paper.get("title", "")
    venue = paper.get("venue", "")
    pub_types = paper.get("publicationTypes") or []

    cite_key = _make_cite_key(paper)
    authors_str = _format_authors(paper)

    # Determine entry type
    if "JournalArticle" in pub_types:
        entry_type = "article"
        venue_key = "journal"
    else:
        entry_type = "inproceedings"
        venue_key = "booktitle"

    lines = [f"@{entry_type}{{{cite_key},"]
    if authors_str:
        lines.append(f"  author = {{{authors_str}}},")
    lines.append(f"  title = {{{title}}},")
    if venue:
        lines.append(f"  {venue_key} = {{{venue}}},")
    if year:
        lines.append(f"  year = {{{year}}},")
    if doi and not _is_arxiv_doi(doi):
        lines.append(f"  doi = {{{doi}}},")
    if arxiv:
        lines.append(f"  url = {{https://arxiv.org/abs/{arxiv}}},")
    elif doi and _is_arxiv_doi(doi):
        arxiv_id = doi.replace("10.48550/arXiv.", "")
        lines.append(f"  url = {{https://arxiv.org/abs/{arxiv_id}}},")
    lines.append("}")
    return "\n".join(lines)


def get_bibtex_for_paper(paper: dict) -> str:
    """Get the best available BibTeX for a paper."""
    ext = paper.get("externalIds") or {}
    doi = ext.get("DOI", "")

    # For papers with a real (non-arXiv) DOI, CrossRef is the most complete source
    if doi and not _is_arxiv_doi(doi):
        bib = get_bibtex_from_crossref(doi)
        if bib:
            return bib

    # Otherwise, build from S2 metadata (reliable, no truncation)
    return build_bibtex_from_metadata(paper)


def inject_placeholder_fields(bibtex: str) -> str:
    """Insert placeholder custom fields before the closing brace of a BibTeX entry."""
    idx = bibtex.rfind("}")
    if idx == -1:
        return bibtex + "\n" + PLACEHOLDER_FIELDS + "\n}"
    inner = bibtex[:idx].rstrip()
    if not inner.endswith(","):
        inner += ","
    return inner + "\n" + PLACEHOLDER_FIELDS + "\n}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    author_ids = [a.strip() for a in SEMANTIC_SCHOLAR_AUTHOR_IDS if a.strip()]

    if not author_ids:
        print("SEMANTIC_SCHOLAR_AUTHOR_IDS is empty.")
        name = input("Enter your name to search Semantic Scholar: ").strip()
        author_id = search_author(name)
        if not author_id:
            sys.exit(1)
        author_ids = [author_id]
        print(f'\nTip: add "{author_id}" to SEMANTIC_SCHOLAR_AUTHOR_IDS in this script to skip this next time.\n')

    bib_paths = [REPO_DIR / f for f in BIB_FILES]
    print(f"Loading existing entries from {', '.join(BIB_FILES)}...")
    known_dois, known_titles, known_arxiv = load_existing_keys(bib_paths)
    print(
        f"  {len(known_dois)} known DOIs, {len(known_titles)} known titles, "
        f"{len(known_arxiv)} known arXiv IDs."
    )

    print(f"\nFetching papers for author ID(s) {', '.join(author_ids)} from Semantic Scholar...")
    papers = fetch_papers_for_authors(author_ids)
    print(f"  {len(papers)} unique papers returned.")

    new_papers = []
    for paper in papers:
        title = paper.get("title", "")
        doi = (paper.get("externalIds") or {}).get("DOI", "")
        arxiv = (paper.get("externalIds") or {}).get("ArXiv", "")
        if doi and _normalize(doi) in known_dois:
            continue
        # Catches papers whose title differs between venues (e.g. a workshop title
        # vs. the arXiv title) as long as one entry records the arXiv ID.
        if arxiv and arxiv.lower() in known_arxiv:
            continue
        if title and _normalize(title) in known_titles:
            continue
        new_papers.append(paper)

    if not new_papers:
        print("\nNo new papers found. You are up to date!")
        return

    print(f"\nFound {len(new_papers)} new paper(s):")
    draft_entries: list[str] = []
    for paper in new_papers:
        title = paper.get("title", "(no title)")
        year = paper.get("year", "?")
        venue = paper.get("venue", "")
        doi = (paper.get("externalIds") or {}).get("DOI", "")
        arxiv = (paper.get("externalIds") or {}).get("ArXiv", "")

        label = f"{title[:60]}{'...' if len(title) > 60 else ''} ({year})"
        meta = " | ".join(filter(None, [venue, f"DOI:{doi}" if doi else "", f"arXiv:{arxiv}" if arxiv else ""]))
        print(f"  - {label}")
        if meta:
            print(f"    {meta}")

        bibtex = get_bibtex_for_paper(paper)
        draft_entries.append(inject_placeholder_fields(bibtex))

    OUTPUT_FILE.write_text(
        "% Auto-generated draft — review, fill in custom fields, then move to the appropriate .bib file.\n\n"
        + "\n\n".join(draft_entries)
        + "\n"
    )
    print(f"\nDraft written to {OUTPUT_FILE.name}")
    print("\nNext steps:")
    print(f"  1. Open {OUTPUT_FILE.name} and review each entry.")
    print("  2. Set website_exclude, website_slug, and keywords.")
    print("  3. Move entries to papers.bib, workshops.bib, or preprints.bib.")
    print(f"  4. Delete {OUTPUT_FILE.name} and commit.")


if __name__ == "__main__":
    main()
