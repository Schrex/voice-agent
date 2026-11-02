"""Spoken needed-by → a day and time in America/New_York (ticket #14). Pure: no I/O.

The parser is strict. Every word has to be understood, or the result is None and nothing is
guessed: the agent then reads the Foreman's words back as said and the Request keeps only them.
What it understands (filler such as "by", "at", "on", "around", "the", "in" is ignored):

- a day: "today", "tomorrow", a weekday ("Tuesday", "this Tuesday": the next one after today);
  "next <weekday>" is not understood (it means different days to different people);
- a clock time: "7", "7:30", "19:00", "seven", "seven thirty", "seven forty-five", with "am"/"pm"
  or "in the morning"/"in the afternoon"/"in the evening";
- a named time: "first thing" and "morning" = FIRST_THING, "noon"/"midday" = NOON,
  "afternoon" = AFTERNOON ("this morning"/"this afternoon" mean today);
- needed at once, said on its own: "now", "right now", "ASAP", "as soon as possible",
  "immediately" = the call's own day and minute (so Today, spec §5).

An hour said without am/pm is read as a work-day hour: 6–11 morning, 12 and 1–5 afternoon
(WORK_DAY_AM_HOURS). A time without a day is the next time it comes round: today if it is still
ahead, else tomorrow. A day without a time keeps the time unknown.

The agent reads the resolved weekday, date and clock time back before the Foreman confirms, so
these conventions are always heard and can be corrected on the call.
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from app.domain.local_time import LOCAL_TZ
from app.domain.urgency import Urgency

FIRST_THING = time(7, 0)
NOON = time(12, 0)
AFTERNOON = time(13, 0)
WORK_DAY_AM_HOURS = range(6, 12)

_FILLER = frozenset({"by", "at", "on", "around", "about", "the", "in", "oclock"})
_WEEKDAYS = {
    name: index
    for index, name in enumerate(
        ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    )
}
_HOUR_WORDS = {
    word: number
    for number, word in enumerate(
        (
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
        ),
        start=1,
    )
}
_MINUTE_WORDS = {"fifteen": 15, "thirty": 30}
# Part of day → (meridiem it implies, time when no clock time is said; None = no default).
_PARTS: dict[str, tuple[str, time | None]] = {
    "morning": ("am", FIRST_THING),
    "afternoon": ("pm", AFTERNOON),
    "evening": ("pm", None),
}
_CLOCK = re.compile(r"^(\d{1,2})(?::(\d{2}))?$")
# Needed at once (spec §5 Today: "needed today or work stopped"): the call's own minute. Said
# alone only; "now" with any other time word is not understood.
_NOW_PHRASES = frozenset(
    {"now", "right now", "asap", "a s a p", "as soon as possible", "immediately"}
)


@dataclass(frozen=True)
class NeededBy:
    """A resolved needed-by: the local day, and the local clock time when one was said."""

    day: date
    time: time | None

    @property
    def at(self) -> datetime | None:
        """The needed-by instant in UTC, or None when only a day was said."""
        if self.time is None:
            return None
        return datetime.combine(self.day, self.time, tzinfo=LOCAL_TZ).astimezone(UTC)


class _Unclear(Exception):
    """Some part of what was said is not understood, or contradicts another part."""


@dataclass
class _Said:
    day: date | None = None
    hour: int | None = None
    minute: int = 0
    meridiem: str | None = None
    part: str | None = None
    named: time | None = None

    def set_day(self, day: date) -> None:
        if self.day is not None and self.day != day:
            raise _Unclear
        self.day = day

    def set_hour(self, hour: int, minute: int) -> None:
        if self.hour is not None or self.named is not None:
            raise _Unclear
        self.hour, self.minute = hour, minute

    def set_named(self, named: time, part: str | None = None) -> None:
        if self.hour is not None or self.named is not None:
            raise _Unclear
        self.named = named
        if part is not None:
            self.set_part(part)

    def set_part(self, part: str) -> None:
        if self.part is not None and self.part != part:
            raise _Unclear
        self.part = part

    def set_meridiem(self, meridiem: str) -> None:
        if self.meridiem is not None:
            raise _Unclear
        self.meridiem = meridiem


def parse_needed_by(spoken: str, now: datetime) -> NeededBy | None:
    """Resolve what the Foreman said against `now` (aware); None when it is not understood."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local_now = now.astimezone(LOCAL_TZ)
    words = _words(spoken)
    if " ".join(words) in _NOW_PHRASES:
        return NeededBy(local_now.date(), time(local_now.hour, local_now.minute))
    try:
        said = _read(words, local_now.date())
        clock = _clock_time(said)
    except _Unclear:
        return None
    if said.day is None:
        if clock is None:
            return None
        today = local_now.date()
        ahead = clock >= local_now.time().replace(tzinfo=None)
        return NeededBy(today if ahead else today + timedelta(days=1), clock)
    return NeededBy(said.day, clock)


def urgency_for(needed_by: NeededBy, now: datetime) -> Urgency:
    """Today when needed on the local day of `now` (or earlier), else Planned (GLOSSARY)."""
    today = now.astimezone(LOCAL_TZ).date()
    return Urgency.TODAY if needed_by.day <= today else Urgency.PLANNED


def speakable(needed_by: NeededBy) -> str:
    """E.g. "Monday, November 2 at 7:00 AM", or "Monday, November 2" without a time."""
    day = f"{needed_by.day:%A}, {needed_by.day:%B} {needed_by.day.day}"
    if needed_by.time is None:
        return day
    hour = needed_by.time.hour % 12 or 12
    meridiem = "AM" if needed_by.time.hour < 12 else "PM"
    return f"{day} at {hour}:{needed_by.time.minute:02d} {meridiem}"


def speakable_at(at: datetime) -> str:
    """An instant as `speakable` reads it, in New York time: "Monday, November 2 at 7:00 AM"."""
    local = at.astimezone(LOCAL_TZ)
    return speakable(NeededBy(local.date(), local.time().replace(tzinfo=None)))


def _words(spoken: str) -> list[str]:
    text = spoken.lower().replace("a.m.", "am").replace("p.m.", "pm").replace("'", "")
    text = re.sub(r"[^a-z0-9:]+", " ", text)
    text = re.sub(r"(\d)(am|pm)\b", r"\1 \2", text)  # "7am", as typed in quick entry
    return text.split()


def _read(words: list[str], today: date) -> _Said:
    said = _Said()
    i = 0
    while i < len(words):
        word = words[i]
        following = words[i + 1] if i + 1 < len(words) else None
        if word in _FILLER:
            pass
        elif word == "today":
            said.set_day(today)
        elif word == "tomorrow":
            said.set_day(today + timedelta(days=1))
        elif word in _WEEKDAYS:
            said.set_day(_next_weekday(today, _WEEKDAYS[word]))
        elif word == "this":
            if following in _PARTS:
                said.set_day(today)
            elif following not in _WEEKDAYS:
                raise _Unclear
        elif word == "first" and following == "thing":
            said.set_named(FIRST_THING, part="morning")
            i += 1
        elif word in ("noon", "midday"):
            said.set_named(NOON)
        elif word in _PARTS:
            said.set_part(word)
        elif word in ("am", "pm"):
            said.set_meridiem(word)
        elif match := _CLOCK.match(word):
            said.set_hour(int(match[1]), int(match[2] or 0))
        elif word in _HOUR_WORDS:
            minute, used = _minute_words(words[i + 1 : i + 3])
            said.set_hour(_HOUR_WORDS[word], minute)
            i += used
        else:
            raise _Unclear
        i += 1
    return said


def _minute_words(after: list[str]) -> tuple[int, int]:
    """Minutes said after an hour word, and how many words they took."""
    if after[:1] and after[0] in _MINUTE_WORDS:
        return _MINUTE_WORDS[after[0]], 1
    if after[:2] == ["forty", "five"]:
        return 45, 2
    return 0, 0


def _next_weekday(today: date, weekday: int) -> date:
    """The next date with that weekday, strictly after today."""
    return today + timedelta(days=(weekday - today.weekday() - 1) % 7 + 1)


def _clock_time(said: _Said) -> time | None:
    part_meridiem, part_time = _PARTS[said.part] if said.part else (None, None)
    if said.named is not None:
        if said.meridiem is not None or (said.part and said.named != part_time):
            raise _Unclear
        return said.named
    if said.hour is None:
        if said.meridiem is not None:
            raise _Unclear
        if said.part is not None and part_time is None:
            raise _Unclear  # "tomorrow evening": no time to resolve to
        return part_time
    if said.minute > 59:
        raise _Unclear
    if said.hour == 0 or said.hour > 12:
        # 24-hour clock ("19:00"): no am/pm or part of day may go with it.
        if said.hour > 23 or said.meridiem or said.part:
            raise _Unclear
        return time(said.hour, said.minute)
    if said.meridiem and part_meridiem and said.meridiem != part_meridiem:
        raise _Unclear
    meridiem = said.meridiem or part_meridiem
    if meridiem is None:
        meridiem = "am" if said.hour in WORK_DAY_AM_HOURS else "pm"
    hour = said.hour % 12 + (12 if meridiem == "pm" else 0)
    return time(hour, said.minute)
