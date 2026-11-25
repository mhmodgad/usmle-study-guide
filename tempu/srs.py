"""A small SM-2-style spaced-repetition scheduler for flashcard reviews.

Ratings (matching the live app's 1-4 keys):
    1 = Again   2 = Hard   3 = Good   4 = Easy

State is persisted in the card_reviews table. schedule() takes the current row
(or None for a brand-new card) and a rating, and returns the updated fields.
"""
import datetime as _dt

MIN_EASE = 1.3
LEARNING_STEPS_MIN = [1, 10]  # minutes for Again / Hard in the learning phase


def _now():
    return _dt.datetime.utcnow()


def _iso(dt):
    return dt.replace(microsecond=0).isoformat() + "Z"


def schedule(row, rating):
    """Return a dict of updated card_reviews fields for a given rating."""
    rating = int(rating)
    now = _now()
    state = (row["state"] if row else None) or "new"
    reps = (row["reps"] if row else 0) or 0
    lapses = (row["lapses"] if row else 0) or 0
    ease = (row["ease"] if row else 2.5) or 2.5
    interval = (row["interval_days"] if row else 0) or 0.0

    if rating <= 1:  # Again
        lapses += 1 if state == "review" else 0
        state = "learning"
        interval = 0
        due = now + _dt.timedelta(minutes=LEARNING_STEPS_MIN[0])
        ease = max(MIN_EASE, ease - 0.20)
    elif state in ("new", "learning"):
        if rating == 2:  # Hard -> short step
            due = now + _dt.timedelta(minutes=LEARNING_STEPS_MIN[1])
            interval = 0
        elif rating == 3:  # Good -> graduate, 1 day
            state = "review"
            interval = 1
            due = now + _dt.timedelta(days=1)
            reps += 1
        else:  # Easy -> graduate, 4 days
            state = "review"
            interval = 4
            due = now + _dt.timedelta(days=4)
            reps += 1
    else:  # review phase, rating >= 2
        if rating == 2:
            ease = max(MIN_EASE, ease - 0.15)
            interval = max(1, round(interval * 1.2))
        elif rating == 3:
            interval = max(1, round((interval or 1) * ease))
        else:  # Easy
            ease = ease + 0.15
            interval = max(1, round((interval or 1) * ease * 1.3))
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
    """Predicted interval label for each rating (1-4) given the current state."""
    return {str(r): _fmt(schedule(row, r)) for r in (1, 2, 3, 4)}


def is_due(due_at):
    if not due_at:
        return True
    try:
        return _dt.datetime.fromisoformat(due_at.replace("Z", "")) <= _now()
    except ValueError:
        return True
