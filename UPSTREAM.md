# Template source and statistics

This profile adapts the actual SVG templates and single-picture README from
[Andrew6rant/Andrew6rant](https://github.com/Andrew6rant/Andrew6rant), revision
`e059bd772121adab3f2a8c7c49d75303d8f39164`.

The template dimensions, styles, typography, dot leaders, and row positions are
retained. The portrait is character art derived directly from the photograph
supplied by Aiman Rosman. Personal fields were supplied by Aiman or read from
his public portfolio on 22 October 2026. Age is the supplied value; no birth
date is inferred. The SVGs in `templates/` retain the upstream structure, with
the original portrait and personal values cleared before personalization.

The public-only updater is an adaptation for this profile, using the built-in
GitHub Actions token. It does not query private repositories or organization
memberships. The original upstream script is not executed.

- Repos: owned public repositories, including forks.
- Contributed: repositories in that same set containing a matching authored
  commit on the captured default branch.
- Stars: stars on owned original public repositories, excluding forks.
- Commits: primary-author matches reachable from those public default branches.
- Lines of Code: summed additions minus deletions in those matching commits,
  including merges. It is a change-history metric, not current source size.
- Shared commit IDs across repositories are counted once for commits/lines.

The `+`/`-` values include documentation and imports; they are not a quality or
original-authorship score. Only aggregate statistics are saved in
`assets/profile-data.json`. A failed API page aborts the update rather than
publishing partial totals. The code requires Python 3.10+ and its standard library.

Run `python today.py` for a live update or
`python today.py --snapshot assets/profile-data.json` to reproduce saved values.
Run `python -m unittest discover -s tests -v` for the offline checks.
