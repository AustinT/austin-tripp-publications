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

## Consumers

- [`AustinT.github.io`](https://github.com/AustinT/AustinT.github.io) — public website.
- `tex-resumes` (private) — CV / resume sources.

Both consume this repo as a git submodule. To pull in updates:

```sh
git submodule update --remote bib
```
