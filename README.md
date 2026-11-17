# Austin Tripp — Publications

BibTeX bibliography for Austin Tripp, split by publication venue type.

## Files

- `preprints.bib` — preprints (not yet peer-reviewed).
- `papers.bib` — peer-reviewed conference and journal publications.
- `workshops.bib` — informal / workshop publications.

## Conventions

- Every entry uses standard BibTeX fields and is consumable by both
  `biblatex` (LaTeX) and Pandoc citeproc (HTML, Quarto). Typst's
  `bibliography()` also reads these files directly.
- The `keywords` field optionally carries:
  - `preprint`, `workshop` — venue-type tag matching the file. Redundant
    with the file the entry lives in, but kept for compatibility with
    biblatex `keyword=`-filter setups.
  - `ownwork` — entries where Austin is the primary contributor (used
    e.g. to mark them with an asterisk in formatted CV output).
- **Keys are stable.** Never rename a citation key, even if its year no longer
  matches the entry (e.g. `fromer2024batched`); the CV and website repos may
  cite it. When a preprint is promoted to a workshop or published paper, move
  the entry between files and keep the key.
- **Status follows the file.** When a paper is accepted, move it from
  `preprints.bib` to `workshops.bib` or `papers.bib`, and update the entry type
  and the `keywords` venue tag to match.
- **`authoritative_link` (usually) holds the arXiv version.** Set it on any workshop or
  published paper that also exists on arXiv. `fetch_new_papers.py` matches
  existing entries by DOI, arXiv ID (read from `authoritative_link`, `journal`,
  `url`, `doi`, etc.) and title, so without it the paper may be proposed as new.
- **Cite under the venue title.** If the venue title differs from the arXiv
  title, keep the venue title as `title` and record the arXiv title in `note`
  (e.g. `tripp2024basic`).
- **One entry per work.** If the same work appeared in several venues, keep a
  single entry for the most authoritative version (e.g. the NeurIPS paper, not
  its earlier workshop version).

## Setup (after cloning)

Enable the committed pre-commit hook — a one-time step per clone:

```sh
git config core.hooksPath .githooks
```

The hook runs `biber --tool` on staged `.bib` files and fails the commit on parse errors. It requires `biber` (ships with most TeX distributions); it skips silently if `biber` is not on your PATH.

## Consumers

- [`AustinT.github.io`](https://github.com/AustinT/AustinT.github.io) — public website.
- `tex-resumes` (private) — CV / resume sources.

Both consume this repo as a git submodule. To pull in updates:

```sh
git submodule update --remote bib
```
