# Contributing to benchboss

Thanks for helping. Bug reports, ideas and pull requests are all welcome.

## Set up

```bash
git clone https://github.com/ValeQRamos/benchboss && cd benchboss
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

You do not need an ESPN league to work on benchboss: `benchboss --demo` and the whole test
suite run on a bundled fictional league (real NBA players and schedule, invented teams and
managers, frozen on a Wednesday of matchup week 3).

## Before you open a pull request

```bash
ruff check src tests tools
pytest
```

- Keep `src/benchboss/core/` free of network and file access so it stays easy to test.
- New ESPN endpoints go through `src/benchboss/espn/client.py` and get documented in
  `docs/api/` (mark what you verified live and what you inferred).
- New read commands need `--json` output and a test in `tests/test_cli.py`.
- Anything that writes to ESPN must ask for confirmation and support `--dry-run`.
- Never commit cookies, private league ids or real people's names. Use the demo league.
- If you change the UI, regenerate the screenshots with `python tools/screenshots.py`.

## Reporting bugs

Open an issue with the command you ran, what you expected, what happened, and the output of
`benchboss status --offline`. Never paste your cookies. If ESPN returned an error, the
`ESPN 409: ...` line is very helpful.

## Ideas

Open an issue or write to [k1lldeer@proton.me](mailto:k1lldeer@proton.me).
