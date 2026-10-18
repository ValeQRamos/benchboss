"""Write docs/commands.md from the argparse definitions (run after changing the CLI)."""

from __future__ import annotations

import argparse
from pathlib import Path

from benchboss.cli import build_parser

OUT = Path(__file__).resolve().parents[1] / "docs" / "commands.md"
GROUPS = [
    ("Look", ["dash", "matchup", "roster", "activity", "standings", "playoffs"]),
    ("Find", ["trash", "players", "fa", "trending", "news", "trades", "alerts"]),
    ("Act (writes to ESPN, always asks first)", ["optimize", "add", "drop", "trade", "watch",
                                                 "chat"]),
    ("Auto-swap (arming a player is your yes; the monitor makes the change)",
     ["autoswap", "monitor"]),
    ("Account", ["setup", "login", "logout", "status", "app"]),
]


def main() -> None:
    ap = build_parser()
    sub = next(a for a in ap._actions if isinstance(a, argparse._SubParsersAction))
    lines = ["# Command reference", "",
             "Generated from the CLI by `python tools/gen_commands_doc.py`. Every command also",
             "accepts the global flags `--json`, `--demo`, `--theme dark|light` and `--yes`.", "",
             "Running `benchboss` with no command opens the interactive app (it needs a terminal).",
             "With `--json`, write commands print one JSON result as well; without `--yes` they",
             "send nothing and exit with code 10.", ""]
    for title, names in GROUPS:
        lines += [f"## {title}", ""]
        for name in names:
            p = sub.choices[name]
            desc = p.description or ""
            lines += [f"### `benchboss {name}`", "", desc[:1].upper() + desc[1:] + ".", ""]
            usage = p.format_usage().replace("usage: ", "").strip()
            lines += ["```text", usage, "```", ""]
            rows = []
            for a in p._actions:
                if a.dest in ("help", "json", "demo", "theme", "yes") or a.help == argparse.SUPPRESS:
                    continue
                flag = ", ".join(a.option_strings) or a.dest
                text = (a.help or "").replace("%%", "%")
                rows.append(f"| `{flag}` | {text[:1].upper() + text[1:]} |")
            if rows:
                lines += ["| Option | Meaning |", "|---|---|", *rows, ""]
    OUT.write_text("\n".join(lines).rstrip() + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
