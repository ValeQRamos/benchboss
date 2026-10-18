# Auto-swap

Some nights a player is listed as day-to-day or out until a few minutes before his game, and
then he plays. If he is on your bench when that happens, you lose his points unless you are
watching. Auto-swap watches for you: you arm the players you are unsure about, and when one of
them turns healthy before his game, benchboss puts him in your lineup and benches the starter
he is worth more than.

It has two parts:

- **Marks.** You arm a player in the app (press `u`) or with `benchboss autoswap add`.
  Arming changes nothing on ESPN by itself.
- **The monitor.** `benchboss monitor` is a process you leave running. It checks your armed
  players, makes the change when one turns healthy, and sends you a notification.

The monitor starts in **trial mode**: it tells you what it would have done ("benchboss would
have started Dyson Daniels at G and benched Scotty Pippen Jr.") and sends nothing to ESPN.
Live mode is there (`--live`), but leave it off until you have seen a week of trial notes
and agree with them. Nobody knows yet how often ESPN changes a status before the game rather
than after it, and trial mode is how you find out for your own players.

## What it does, exactly

A player **turns healthy** when his ESPN status goes from day-to-day, questionable, doubtful,
out or suspended to active or probable. A move from out to day-to-day does not count. Neither
does a player whose status ESPN did not send: an unknown status is never treated as healthy.

When an armed player turns healthy, at least 3 minutes before his game, benchboss:

1. Reads your lineup again and checks that this read also shows him healthy. If the two reads
   disagree, it waits and looks again on the next round.
2. Plans the day like Optimize does, except that only he and one starter may change between
   bench and lineup. The starter who sits is the one with the lowest value
   that day (ESPN's projection, times 75% for day-to-day and questionable players) whose game
   has not started. Starters can trade slots so he fits (a guard moving from G to UT, for
   example), but nobody else goes in or out.
3. Skips the change if it adds less than 1 projected point.
4. Sends it (live mode) or tells you what it would have sent (trial mode).

It never touches a player whose game has started or starts within 3 minutes, a player on
IR, or a game whose time ESPN has not set yet. It only writes today's lineup, and only when
ESPN agrees that today is today.

A change today carries over to the next days that have no changes of their own. After a live
change the note says so; run `benchboss optimize tomorrow` (or press `t` tomorrow) to set the
next day.

## Arming players

In the app, press `u` for the Auto-swap screen. Every player on your roster has a row with
his status, today's tip time and what benchboss would do if he turned healthy right now.

| Key | What it does |
|---|---|
| `enter` | Shows what would happen and asks. Press `enter` again (after a short pause) to arm him. Any other key cancels |
| `enter`, `backspace` or `delete` on an armed player | Disarms him at once |
| `!` | Alert only: you get a note when he turns healthy, and the lineup is never changed. No question, since nothing on ESPN changes. On an armed player it lowers him to alert only |
| `esc` | Cancels the question, or goes back to the menu |

From the command line:

```bash
benchboss autoswap                                # who is armed, what each would do, is the monitor running
benchboss autoswap add "Dyson Daniels" --dry-run  # only show what would happen
benchboss autoswap add "Dyson Daniels"            # show it, then ask
benchboss autoswap add "Coby White" --notify-only # an alert, no lineup change, no question
benchboss autoswap add "Dyson Daniels" --today    # the mark ends tonight
benchboss autoswap remove "Dyson Daniels"
benchboss autoswap clear                          # take every mark off
benchboss autoswap pause                          # the monitor changes nothing until resume
benchboss autoswap resume
benchboss autoswap log -n 20                      # every lineup change and auto-swap decision
```

A mark lasts until the end of the matchup week (Sunday) unless you pass `--today`. Arming a
player is your yes for that player: from then on the monitor may change your lineup for him
without asking again, so the confirmation always shows what would happen first. Removing,
clearing and pausing never ask, because they only lower the risk.

The Roster screen shows a `✓` after an armed player and a `!` after an alert-only one.

## Watch-list alerts

The monitor also checks the players on your ESPN watch list. When one of them turns healthy
you get a note ("Ausar Thompson is healthy (was OUT). Tips 7:00 PM."), marked urgent when his
game is today and has not started. Only that change makes a note; the rest are kept in the
log. The app's Inbox (`i`) and `benchboss alerts` show the same alerts.

## Running the monitor

```bash
benchboss monitor                        # trial mode, until Ctrl-C
benchboss monitor --notify mac,ntfy      # pick where the notes go
benchboss monitor --once                 # one round, then exit (for cron)
benchboss monitor --once --dry-run       # print what it sees and would do; saves and sends nothing
benchboss monitor --live --yes           # live mode: it changes your lineup on ESPN
```

It reads one small list of players per round: more often as the earliest armed game gets
close (every 30 minutes when it is more than 6 hours away, every 30 seconds in the last 10
minutes) and every 30 minutes when no armed player has a game left today. Watch-list players
ride along on the same read. If your computer sleeps, the monitor checks everything as soon
as it wakes up.

With `--once` from cron, the Auto-swap screen and `autoswap list` count the monitor as running
for 15 minutes after each round, so run it at least that often.

Only one monitor runs per league. A second one, on this computer or another sharing the same
settings folder, stops with a message. If the first one died, the second one takes over after
3 minutes.

When something goes wrong, the loop keeps going and tells you once a day:

- Cookies expired: "benchboss cannot read your league: run benchboss login". It stops reading
  and writing and tries again every 10 minutes, so a new `benchboss login` in another
  terminal fixes it without a restart. Close to an armed game, it reads a second time before
  it believes the cookies are bad.
- ESPN down or slow: it waits 30 seconds, then 60, 120 and 240, but never longer than half the
  time left before an armed game.
- ESPN blocking the machine (HTTP 403 or 429): the same, plus a note.

`--once` exits with `0` when all went well, `3` when it could not read the league, `4` when
ESPN refused a live change or did not confirm it, and `5` when a safety check stopped a
change. `--json` prints one JSON object per event, the same records as the log.

### Live mode and its limits

Live mode only runs in leagues where each player's lineup locks at his own game (ESPN's
"individual game" lock, the default for daily leagues), during the season, and never in the
demo. On top of the checks above:

- It saves what it is about to send before sending it, so a restart in the middle never sends
  a change twice or loses count.
- It checks the lease right before every write, so a monitor that lost it never writes.
- It reads your marks again right before every write, so disarming or pausing always wins.
- It reads your lineup again at least 20 seconds after a write and logs whether ESPN shows the
  change. When ESPN's answer got lost on the way, it sends the change once more, only if that
  read shows nothing was applied and the game is still more than 3 minutes away.
- A change ESPN refuses is never retried. Two refusals in one day turn the rest of the day into
  trial mode, with a note.
- At most 6 automatic changes a day, at most 2 per player, and 60 seconds between changes
  unless a game starts within 2 minutes.
- If a player it started is ruled out, suspended or doubtful before his game, it puts him back
  on the bench and the starter he replaced back in. It checks this on every read until it is
  done, so a lineup read that is a step behind (or fails) is tried again on the next one. If
  nobody can take his spot, or his game is less than 3 minutes away, you get an urgent note.
- If someone else (you in the ESPN app, a script) moved an armed player since the monitor last
  looked, that mark rests for the rest of the day and you get a note.

Keep one automatic writer per team. If you also optimize every morning with your own script,
that is fine: the monitor reads the lineup again before every change and only touches the
armed player and the starter he replaces.

## Notifications

Pick any of these with `--notify`, or save a default in `config.json`:

```json
{"notify": {"backends": ["mac", "ntfy"]}}
```

| Backend | What it does | What it needs |
|---|---|---|
| `mac` | macOS Notification Center (the default on a Mac) | nothing |
| `ntfy` | A push to the free [ntfy](https://ntfy.sh) app on iPhone or Android | `BENCHBOSS_NTFY_TOPIC`; optional `BENCHBOSS_NTFY_TOKEN` and `BENCHBOSS_NTFY_SERVER` |
| `cmd` | Runs your own command (Telegram, Pushover, anything) | `BENCHBOSS_NOTIFY_CMD` |
| `log` | One line on the screen or in the service log (the default elsewhere) | nothing |

Secrets never go on the command line or in `config.json`. Set them in the environment, or put
them in `notify.env` in the settings folder (`~/.config/benchboss/notify.env`), one
`NAME=value` per line. benchboss only reads that file when nobody else can (`chmod 600`).

```bash
# ~/.config/benchboss/notify.env
BENCHBOSS_NTFY_TOPIC=benchboss-k3x9q2mfw8pz4r7t
```

On the public ntfy server anyone who knows a topic can read it, so pick a long random one and
subscribe to it in the ntfy app. Names with accents (Jokić, Dončić) arrive intact.

The command backend runs your command without a shell. The title and text are in the
`BENCHBOSS_TITLE` and `BENCHBOSS_TEXT` environment variables (and `BENCHBOSS_PRIORITY`:
urgent, normal or info), and the text also comes on standard input. For example, a small
script for a Telegram bot:

```bash
#!/bin/sh
# ~/bin/tell-me (chmod 700); BENCHBOSS_NOTIFY_CMD=/Users/you/bin/tell-me
curl -s "https://api.telegram.org/bot$TELEGRAM_TOKEN/sendMessage" \
  --data-urlencode chat_id="$TELEGRAM_CHAT" \
  --data-urlencode text="$BENCHBOSS_TITLE: $BENCHBOSS_TEXT" > /dev/null
```

Try your setup with `benchboss monitor --notify-test`. Each note goes out once, since the
monitor remembers what it sent that day. A note that timed out is not sent again, since it may have
arrived. Notes carry player names and what happened, never your league id or cookies. Only
the monitor sends notes; the app shows the same alerts in its Inbox.

## Keeping it running

The monitor only works while the computer running it is awake and online. A laptop that
sleeps at night misses the games; a Mac mini, a home server or a small cloud machine is a
better home.

- **tmux or screen** (simplest): `tmux new -d -s benchboss 'benchboss monitor'`. It does not
  survive a reboot.
- **macOS (launchd):** install benchboss with `uv tool install
  git+https://github.com/ValeQRamos/benchboss`, not from a folder in Desktop, Documents or
  Downloads, which launchd cannot read. Create the log folder (`mkdir -p
  ~/.config/benchboss/logs`), save this as
  `~/Library/LaunchAgents/io.github.valeqramos.benchboss.monitor.plist` (with your own paths)
  and run `launchctl load` on it:

  ```xml
  <?xml version="1.0" encoding="UTF-8"?>
  <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
  <plist version="1.0"><dict>
    <key>Label</key><string>io.github.valeqramos.benchboss.monitor</string>
    <key>ProgramArguments</key><array>
      <string>/Users/you/.local/bin/benchboss</string><string>monitor</string>
      <string>--notify</string><string>mac,ntfy</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
    <key>ThrottleInterval</key><integer>60</integer>
    <key>StandardOutPath</key><string>/Users/you/.config/benchboss/logs/monitor.log</string>
    <key>StandardErrorPath</key><string>/Users/you/.config/benchboss/logs/monitor.log</string>
  </dict></plist>
  ```

  A LaunchAgent runs in your login session, so it can read the cookies from your keychain.

- **Linux (systemd):** `~/.config/systemd/user/benchboss-monitor.service`, then
  `systemctl --user enable --now benchboss-monitor` and `loginctl enable-linger $USER`:

  ```ini
  [Unit]
  Description=benchboss monitor
  StartLimitIntervalSec=600

  [Service]
  ExecStart=%h/.local/bin/benchboss monitor --notify ntfy,log
  Restart=on-failure
  RestartSec=60
  RestartPreventExitStatus=2 3 10
  Environment=TZ=America/Chicago
  # a server has no keychain: run `benchboss login --manual` once (it saves the cookies in a
  # file only you can read) or set ESPN_S2 and ESPN_SWID in an EnvironmentFile (chmod 600)

  [Install]
  WantedBy=default.target
  ```

  Set `TZ` to your own time zone: tip times in the notes use the machine's clock.

- **Windows:** Task Scheduler, "At log on", running `benchboss monitor --notify log`.

To turn on live mode, add `--live --yes` to the command. Do it once a week of trial notes has
shown you that the changes it would make are the ones you want.

## Files

All in the settings folder (`~/.config/benchboss`, or `BENCHBOSS_HOME`), private to you:

| File | What it holds |
|---|---|
| `leagues/<league id>/marks.json` | Your marks and the pause switch. A damaged file counts as no marks |
| `leagues/<league id>/monitor.json` | The monitor's state: last statuses, today's changes and counts, its alerts. The app only reads it |
| `leagues/<league id>/monitor.lock` | The lease that keeps it to one monitor per league |
| `logs/lineup-YYYY-MM.jsonl` | Every lineup change (Apply in the app, `optimize`, the monitor) and every auto-swap decision, one JSON object per line |
| `notify.env` | Your notification secrets, only read when private |

Marks set on one computer stay on that computer. Arm players on the machine that runs the
monitor (over SSH, for example).

## Try it in the demo

```bash
benchboss --demo monitor --once --simulate "Dyson Daniels=ACTIVE"
```

The demo starts from the lineup Optimize would set that morning, with Dyson Daniels
(day-to-day) on the bench. The command pretends he turned healthy and prints what auto-swap
would do: start him at G and bench Scotty Pippen Jr. Nothing is saved or sent. In the app
(`benchboss --demo`, then `u`) you can arm and disarm players; the demo keeps the marks only
while the app is open.

`--simulate "Player=STATUS"` works on your own league too, in trial mode or with `--dry-run`,
to see what the monitor would do. It is refused with `--live`.

## For AI agents

Arming a player is the user's yes for an automatic lineup change. Agents preview with
`benchboss autoswap add "Player" --dry-run` and arm only after the user says yes. They never
start the monitor: it runs until stopped, and with `--live` it writes without asking. The one
monitor command an agent runs on its own is `benchboss monitor --once --dry-run --json`. See
[AGENTS.md](../AGENTS.md).
