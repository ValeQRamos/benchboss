"""Lookup tables for ESPN Fantasy Basketball ids (game code ``fba``).

Verified against live league payloads and ESPN's web client. See docs/api/README.md.
"""

from __future__ import annotations

GAME = "fba"

# Lineup slot ids (rosterSettings.lineupSlotCounts keys, roster entries lineupSlotId)
SLOT = {0: "PG", 1: "SG", 2: "SF", 3: "PF", 4: "C", 5: "G", 6: "F", 7: "SG/SF", 8: "G/F",
        9: "PF/C", 10: "F/C", 11: "UT", 12: "BE", 13: "IR", 15: "Rookie"}
SLOT_ID = {v: k for k, v in SLOT.items()}
BENCH, IR = 12, 13
POSITION_SLOTS = (0, 1, 2, 3, 4)  # the five real positions inside eligibleSlots

# player.defaultPositionId
POSITION = {1: "PG", 2: "SG", 3: "SF", 4: "PF", 5: "C", 6: "G", 7: "F", 8: "UT"}
POSITION_TO_SLOT = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4}

# player.proTeamId
PRO_TEAM = {0: "FA", 1: "ATL", 2: "BOS", 3: "NOP", 4: "CHI", 5: "CLE", 6: "DAL", 7: "DEN",
            8: "DET", 9: "GSW", 10: "HOU", 11: "IND", 12: "LAC", 13: "LAL", 14: "MIA", 15: "MIL",
            16: "MIN", 17: "BKN", 18: "NYK", 19: "ORL", 20: "PHI", 21: "PHX", 22: "POR",
            23: "SAC", 24: "SAS", 25: "OKC", 26: "UTA", 27: "WSH", 28: "TOR", 29: "MEM",
            30: "CHA"}

# player.injuryStatus -> short tag (bereavement and paternity leave read as OUT)
INJURY_TAG = {"ACTIVE": "", "NORMAL": "", "DAY_TO_DAY": "DTD", "OUT": "OUT",
              "SUSPENSION": "SUSP", "INJURY_RESERVE": "IR", "QUESTIONABLE": "Q",
              "PROBABLE": "P", "DOUBTFUL": "D", "BEREAVEMENT": "OUT", "PATERNITY": "OUT"}

# How much of a player's projection we trust for a given status when planning lineups.
INJURY_FACTOR = {"OUT": 0.0, "SUSPENSION": 0.0, "INJURY_RESERVE": 0.0, "BEREAVEMENT": 0.0,
                 "PATERNITY": 0.0, "DOUBTFUL": 0.25, "DAY_TO_DAY": 0.75, "QUESTIONABLE": 0.75}

# player.injuryStatus by what it means for a lineup. Auto-swap, the lineup guards and the
# monitor's alerts all use these sets. A status outside KNOWN_STATUSES, or no status at all
# (Player.injury_known is False), is "unknown": never healthy, so it never triggers an
# automatic lineup change.
HEALTHY_STATUSES = frozenset({"ACTIVE", "NORMAL", "PROBABLE"})
RISK_STATUSES = frozenset({"DAY_TO_DAY", "QUESTIONABLE", "DOUBTFUL"})
OUT_STATUSES = frozenset({"OUT", "SUSPENSION", "INJURY_RESERVE", "BEREAVEMENT", "PATERNITY"})
KNOWN_STATUSES = HEALTHY_STATUSES | RISK_STATUSES | OUT_STATUSES


def status_class(status: str | None) -> str:
    """ "ok", "risk", "out", or "unknown" for None, "" and any status not in KNOWN_STATUSES."""
    if status in HEALTHY_STATUSES:
        return "ok"
    if status in RISK_STATUSES:
        return "risk"
    if status in OUT_STATUSES:
        return "out"
    return "unknown"


# rosterSettings.rosterLocktimeType: adds and drops made after the day's first tip-off only
# take effect the next day.
ROSTER_LOCK_FIRST_GAME = "FIRSTGAME_SCORINGPERIOD"
# rosterSettings.lineupLocktimeType: each player's lineup slot locks at his own tip-off. The
# monitor only makes automatic lineup changes in leagues that lock this way.
LINEUP_LOCK_INDIVIDUAL = "INDIVIDUAL_GAME"

# Stat ids used by points leagues (scoringSettings.scoringItems[].statId)
STAT = {0: "PTS", 1: "BLK", 2: "STL", 3: "AST", 4: "OREB", 5: "DREB", 6: "REB", 7: "EJ",
        8: "FF", 9: "PF", 10: "TF", 11: "TO", 12: "DQ", 13: "FGM", 14: "FGA", 15: "FTM",
        16: "FTA", 17: "3PM", 18: "3PA", 19: "FG%", 20: "FT%", 21: "3P%", 37: "DD",
        38: "TD", 39: "QD", 40: "MIN", 41: "GS", 42: "GP"}

# Box score stat ids, by name (the keys of stats[].averageStats and stats[].stats). In
# averageStats the percentages are fractions (0.46) and MIN is minutes per game.
PTS, BLK, STL, AST, OREB, DREB, REB, TO = 0, 1, 2, 3, 4, 5, 6, 11
FGM, FGA, FTM, FTA, TPM, TPA, FG_PCT, FT_PCT, TP_PCT = 13, 14, 15, 16, 17, 18, 19, 20, 21
DD, TD, MIN, GS, GP = 37, 38, 40, 41, 42

# stats[].id is "{statSourceId}{statSplitTypeId}{seasonId}": source 0 = actual, 1 = projected;
# split 0 = season, 1 = last 7 days, 2 = last 15, 3 = last 30.
SOURCE_ACTUAL, SOURCE_PROJECTED = 0, 1
SPLIT_SEASON, SPLIT_LAST7, SPLIT_LAST15, SPLIT_LAST30 = 0, 1, 2, 3

# The stat splits benchboss reads for every player: key -> (source, split, seasons back).
# "last" is last season's actual average, the only real numbers before opening night.
SPLITS = {"season": (SOURCE_ACTUAL, SPLIT_SEASON, 0), "l7": (SOURCE_ACTUAL, SPLIT_LAST7, 0),
          "l15": (SOURCE_ACTUAL, SPLIT_LAST15, 0), "l30": (SOURCE_ACTUAL, SPLIT_LAST30, 0),
          "proj": (SOURCE_PROJECTED, SPLIT_SEASON, 0), "last": (SOURCE_ACTUAL, SPLIT_SEASON, 1)}
SPLIT_LABEL = {"season": "Season", "l7": "Last 7", "l15": "Last 15", "l30": "Last 30",
               "proj": "Projected", "last": "Last season"}
SPLIT_SHORT = {"season": "Avg", "l7": "L7", "l15": "L15", "l30": "L30", "proj": "Proj",
               "last": "Prev"}


def stat_key(source: int, split: int, season: int) -> str:
    return f"{source}{split}{season}"


def split_ids(season: int) -> list[str]:
    """The stats[].id of every split in SPLITS, for filterStatsForTopScoringPeriodIds."""
    return [stat_key(src, split, season - back) for src, split, back in SPLITS.values()]
