# Using benchboss in VS Code

benchboss is a terminal app, so it runs anywhere VS Code has a terminal. This page covers the
three ways people use it there.

## 1. The app in the terminal panel

Open the integrated terminal and run:

```bash
benchboss
```

Every screen has a one-key shortcut shown in the footer. The app does not use `ctrl+p`
(VS Code keeps that shortcut for itself).

## 2. A live side panel

Split the terminal and run the dashboard in the narrow half:

```bash
benchboss dash --watch          # refreshes every 60 s
benchboss dash --watch 30       # every 30 s (minimum 15)
```

The layout adapts to the width: one column below 92 columns, two or three columns on wider
terminals.

## 3. Tasks

When you open a clone of this repository, `Tasks: Run Task` in the command palette lists:

| Task | Runs |
|---|---|
| benchboss: app | `benchboss` |
| benchboss: dashboard (side panel) | `benchboss dash --watch` |
| benchboss: optimize today | `benchboss optimize today` (asks before sending) |
| benchboss: optimize week | `benchboss optimize week` (asks before sending) |
| benchboss: best trash | `benchboss trash` |
| benchboss: news | `benchboss news --days 5` |
| benchboss: demo | `benchboss --demo` |

To use them in your own folder, copy [`.vscode/tasks.json`](../.vscode/tasks.json).

## 4. GitHub Copilot agent mode

The repository ships everything an agent needs to drive benchboss safely:

| File | Purpose |
|---|---|
| [`AGENTS.md`](../AGENTS.md) | Full instructions: commands, JSON output, the write protocol, exit codes |
| [`.github/copilot-instructions.md`](../.github/copilot-instructions.md) | The short list of rules Copilot always loads |
| [`.github/skills/`](../.github/skills) | Skills: lineup optimizer, trash scout, trade finder, player news, matchup report |
| [`.github/agents/benchboss.agent.md`](../.github/agents/benchboss.agent.md) | A custom "benchboss" agent with terminal access and no file editing |
| [`.vscode/settings.json`](../.vscode/settings.json) | Lets the agent run read commands and `--dry-run` previews without asking every time. Writes (including `watch add` and `watch remove`), anything with `--yes` or `-y`, `news --ai` (a paid call), `alerts --mark-read` (it marks your watch list news as read) and `dash --watch` (it never exits) always ask |

Open the folder, start Copilot Chat in agent mode and talk normally:

- "How is my matchup going?"
- "Set my lineup for the rest of the week." (it previews with `--dry-run`, then asks you)
- "Who is the best pickup this week? I can drop my worst guy."
- "News on my players from the last 5 days."
- "I need a center. Find me a fair trade."

Writes always need your explicit yes in the chat; the agent then runs the command with
`--yes` and shows you ESPN's answer.

## Light themes

On a light VS Code theme, choose **light** during `benchboss setup`, run with
`--theme light`, or press `ctrl+t` inside the app to switch.

## Troubleshooting

- **Garbled boxes or colors:** VS Code's terminal supports true color; if rendering looks off,
  try turning off `terminal.integrated.gpuAcceleration`.
- **A key does nothing:** VS Code may be using that shortcut. Every action also has a menu
  entry you can select with the arrow keys and Enter.
