"""The default weekly plan for a fresh account.

Lives here rather than in the UI because "what does my default week look like"
is a property of the data, and because creating it server side happens in a
single transaction.
"""

from __future__ import annotations

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri")
WEEKEND = ("Sat", "Sun")

_WEEKDAY = [
    ("06:30", "Get up", "morning"),
    ("07:15", "School", "school"),
    ("15:30", "Break", "other"),
    ("16:00", "Homework / study", "school"),
    ("17:30", "Training (gymnastics)", "training"),
    ("19:30", "Computer science / security", "infosec"),
    ("21:30", "Free time", "other"),
    ("22:30", "Bedtime", "other"),
]

_WEEKEND = [
    ("09:00", "Get up", "morning"),
    ("10:00", "Training", "training"),
    ("13:00", "Computer science / CTF", "infosec"),
    ("17:00", "Freelance project", "freelance"),
    ("23:00", "Bedtime", "other"),
]

# (weekday, time, title, category)
DEFAULT_BLOCKS: list[tuple[str, str, str, str]] = [
    (day, time, title, category)
    for day in WEEKDAYS
    for time, title, category in _WEEKDAY
] + [
    (day, time, title, category)
    for day in WEEKEND
    for time, title, category in _WEEKEND
]

# (weekday, title, category)
DEFAULT_TODOS: list[tuple[str, str, str]] = [
    ("Mon", "Finish chemistry homework", "school"),
    ("Mon", "Solve one CTF challenge", "infosec"),
]
