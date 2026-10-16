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

## Adding a screen

Every screen is one module in `src/benchboss/ui/screens/`, and the app and the command line
both draw from it. `workload.py` is a good small one to copy; `finder.py` and `playoffs.py`
are the interactive ones. The protocol is in `ui/screens/__init__.py`. In short:

1. Create `ui/screens/yours.py` with:
   - `TITLE`, the heading.
   - `VIEWS`, a tuple of `(key, label)` pairs, or `()`. The app cycles them with `v`; the CLI
     takes `--view KEY`.
   - `load(session, **options)`. The only function that talks to ESPN. It runs in a worker
     thread in the app and may raise `BenchbossError`, which the app shows as the message.
   - `draw(data, pal, width, view=0)`. Returns a Rich renderable no wider than `width`. It
     never calls ESPN, because a resize or `ctrl+t` draws again from the same data. Check it
     in both palettes and at 46, 80 and 120 columns.
   - `to_json(data)`. What `--json` prints. Keep the keys stable once released.
   - Optionally `widget(data, app)`, a Textual widget the app mounts instead of the drawing.
     Keys it does not bind fall through to the app's menu keys.
2. Add it to `SCREENS` in `ui/screens/__init__.py` and give it a `MENU` entry in `ui/app.py`
   with a free key (taken: `d t w a f p n x i s y o`, plus `g v m r q`).
3. Add a command in `cli.py` that calls `_screen(c, yours)`, with `--view` when there are
   views, add it to `GROUPS` in `tools/gen_commands_doc.py`, and regenerate
   `docs/commands.md` with `python tools/gen_commands_doc.py`.
4. Write tests on the demo league (`tests/test_workload.py` shows the pattern), and if the
   README should show it, add its key to `tools/screenshots.py`.

## Reporting bugs

Open an issue with the command you ran, what you expected, what happened, the output of
`benchboss --version`, your OS and terminal, and whether `benchboss status --offline` says
the cookies were found. If ESPN returned an error, the `ESPN 409: ...` line is very helpful.

Issues are public. Never paste your cookies, and do not paste the full `status` output: it
shows your league id, your league and team names and your home folder path. Replace those
with placeholders in anything you paste.

## Ideas

Open an issue or write to [k1lldeer@proton.me](mailto:k1lldeer@proton.me).
