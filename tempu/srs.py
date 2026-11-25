"""SM-2 spaced-repetition scheduler for flashcard reviews.

Ratings (matching the live app's 1-4 keys):
    1 = Again   2 = Hard   3 = Good   4 = Easy

Three states are persisted in card_reviews.state:
    new       -> never answered
    learning  -> in the short-interval steps (also used while relearning a lapse)
    review    -> graduated; interval grows in days

schedule(row, rating) takes the current card_reviews row (or None for a brand-new
card) and a rating, and returns the updated fields. preview(row) returns the
interval label each rating would produce, for the study UI.
"""
import datetime as _dt
import random as _random

# --- tunables ---------------------------------------------------------------
MIN_EASE = 1.3
STARTING_EASE = 2.5
LEARNING_STEPS_MIN = [1, 10]   # Again / Hard steps while learning a new card (minutes)
RELEARN_STEP_MIN = 10          # step shown after a lapse (minutes)
GRADUATING_INTERVAL = 1        # days — Good graduates a learning card
EASY_INTERVAL = 4              # days — Easy graduates a learning card
SECOND_INTERVAL = 6            # days — Good on the first review after graduating
HARD_MULT = 1.2                # Hard interval multiplier
EASY_BONUS = 1.3               # extra multiplier for Easy in review
HARD_PENALTY = 0.15            # ease drop on Hard
LAPSE_PENALTY = 0.20           # ease drop on a lapse (Again in review)
EASY_REWARD = 0.15             # ease gain on Easy
MAX_INTERVAL = 365             # cap, days
FUZZ = 0.05                    # ±5% spread on multi-day intervals


def _now():
    return _dt.datetime.utcnow()


def _iso(dt):
    return dt.replace(microsecond=0).isoformat() + "Z"


def _clamp_days(d, fuzz):
    """Round to whole days, apply a small spread, and cap."""
    d = int(round(d))
    if fuzz and d >= 3:
        j = max(1, round(d * FUZZ))
        d += _random.randint(-j, j)
    return max(1, min(MAX_INTERVAL, d))


def schedule(row, rating, fuzz=True):
    """Return a dict of updated card_reviews fields for a given rating."""
    rating = int(rating)
    now = _now()
    state = (row["state"] if row else None) or "new"
    reps = (row["reps"] if row else 0) or 0
    lapses = (row["lapses"] if row else 0) or 0
    ease = (row["ease"] if row else STARTING_EASE) or STARTING_EASE
    interval = (row["interval_days"] if row else 0) or 0.0

    if state in ("new", "learning"):
        if rating <= 1:            # Again -> first learning step
            state = "learning"
            interval = 0
            due = now + _dt.timedelta(minutes=LEARNING_STEPS_MIN[0])
        elif rating == 2:          # Hard -> later learning step
            state = "learning"
            interval = 0
            due = now + _dt.timedelta(minutes=LEARNING_STEPS_MIN[-1])
        elif rating == 3:          # Good -> graduate
            state = "review"
            reps += 1
            interval = GRADUATING_INTERVAL
            due = now + _dt.timedelta(days=interval)
        else:                      # Easy -> graduate with a longer first step
            state = "review"
            reps += 1
            interval = EASY_INTERVAL
            due = now + _dt.timedelta(days=interval)
    else:  # review
        if rating <= 1:            # lapse -> relearn
            lapses += 1
            ease = max(MIN_EASE, ease - LAPSE_PENALTY)
            state = "learning"
            interval = 0
            due = now + _dt.timedelta(minutes=RELEARN_STEP_MIN)
        else:
            if rating == 2:        # Hard
                ease = max(MIN_EASE, ease - HARD_PENALTY)
                interval = _clamp_days(max(interval, 1) * HARD_MULT, fuzz)
            elif rating == 3:      # Good
                base = SECOND_INTERVAL if interval <= GRADUATING_INTERVAL else interval * ease
                interval = _clamp_days(base, fuzz)
            else:                  # Easy
                ease = ease + EASY_REWARD
                base = SECOND_INTERVAL if interval <= GRADUATING_INTERVAL else interval * ease
                interval = _clamp_days(base * EASY_BONUS, fuzz)
            reps += 1
            due = now + _dt.timedelta(days=interval)

    return {
        "state": state,
        "reps": reps,
        "lapses": lapses,
        "ease": round(ease, 3),
        "interval_days": interval,
        "due_at": _iso(due),
        "last_rating": rating,
        "last_reviewed_at": _iso(now),
    }


def _fmt(upd):
    """Human interval label for a scheduled result, e.g. '10m', '1d', '2mo'."""
    now = _now()
    try:
        due = _dt.datetime.fromisoformat(upd["due_at"].replace("Z", ""))
    except (ValueError, TypeError, KeyError):
        return ""
    secs = max(0, (due - now).total_seconds())
    mins = secs / 60
    if mins < 60:
        return "%dm" % max(1, round(mins))
    hours = mins / 60
    if hours < 24:
        return "%dh" % round(hours)
    days = hours / 24
    if days < 30:
        return "%dd" % round(days)
    if days < 365:
        return "%dmo" % round(days / 30)
    return "%.1fy" % (days / 365)


def preview(row):
    """Interval label each rating (1-4) would produce (deterministic: no fuzz)."""
    return {str(r): _fmt(schedule(row, r, fuzz=False)) for r in (1, 2, 3, 4)}


def is_due(due_at):
    if not due_at:
        return True
    try:
        return _dt.datetime.fromisoformat(due_at.replace("Z", "")) <= _now()
    except ValueError:
        return True
