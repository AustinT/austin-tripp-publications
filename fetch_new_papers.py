#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "bibtexparser>=1.4",
#   "requests>=2.31",
# ]
# ///
"""
Fetch new papers from Semantic Scholar and produce a draft BibTeX file.

Usage:
    uv run fetch_new_papers.py

The script compares papers returned by the Semantic Scholar author API against
all entries in papers.bib, workshops.bib, and preprints.bib. New papers are
written to new_papers_draft.bib with placeholder custom fields for manual review.

Configuration: set SEMANTIC_SCHOLAR_AUTHOR_ID below, or find your ID at
https://www.semanticscholar.org by searching your name — the URL contains a
numeric ID like /author/Austin-Tripp/2145663280.
"""

import re
import sys
import unicodedata
from pathlib import Path

import bibtexparser
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SEMANTIC_SCHOLAR_AUTHOR_ID = "115766771"  # Austin Tripp — update if this is wrong
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


def load_existing_keys(bib_files: list[Path]) -> tuple[set[str], set[str]]:
    """Return (normalized DOIs, normalized titles) from existing bib files."""
    dois: set[str] = set()
    titles: set[str] = set()
    for path in bib_files:
        if not path.exists():
            continue
        lib = bibtexparser.load(open(path))
        for entry in lib.entries:
            if doi := entry.get("doi", "").strip():
                dois.add(_normalize(doi))
            if title := entry.get("title", "").strip():
                titles.add(_normalize(title))
    return dois, titles


def search_author(name: str) -> str | None:
    """Interactive: search Semantic Scholar for an author and return their ID."""
    resp = requests.get(
        f"{SS_API_BASE}/author/search",
        params={"query": name, "fields": "name,affiliations,paperCount"},
        timeout=15,
    )
    resp.raise_for_status()
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
        "fields": "title,year,authors,externalIds,venue,publicationTypes",
        "limit": 200,
    }
    papers: list[dict] = []
    while True:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        body = resp.json()
        papers.extend(body.get("data", []))
        if not (token := body.get("next")):
            break
        params["token"] = token
    return papers


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
    author_id = SEMANTIC_SCHOLAR_AUTHOR_ID.strip()

    if not author_id:
        print("SEMANTIC_SCHOLAR_AUTHOR_ID is not set.")
        name = input("Enter your name to search Semantic Scholar: ").strip()
        author_id = search_author(name)
        if not author_id:
            sys.exit(1)
        print(f'\nTip: set SEMANTIC_SCHOLAR_AUTHOR_ID = "{author_id}" in this script to skip this next time.\n')

    bib_paths = [REPO_DIR / f for f in BIB_FILES]
    print(f"Loading existing entries from {', '.join(BIB_FILES)}...")
    known_dois, known_titles = load_existing_keys(bib_paths)
    print(f"  {len(known_dois)} known DOIs, {len(known_titles)} known titles.")

    print(f"\nFetching papers for author ID {author_id} from Semantic Scholar...")
    papers = fetch_author_papers(author_id)
    print(f"  {len(papers)} papers returned.")

    new_papers = []
    for paper in papers:
        title = paper.get("title", "")
        doi = (paper.get("externalIds") or {}).get("DOI", "")
        if doi and _normalize(doi) in known_dois:
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
