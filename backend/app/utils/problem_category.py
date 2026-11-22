"""Problem categories of maintenance tickets (B4).

The database has no category column (the schema is frozen): the category is stored as a prefix of
`maintenance_tickets.problem_description`, e.g.

    "[Power issue] The device won't turn on"

The labels and the parsing rule are IDENTICAL to the mobile app
(mobile/lib/features/tickets/domain/ticket.dart, ProblemCategory / ProblemDescription), so both
sides always read a stored description the same way:

- `compose` writes "[<label>] <description trimmed>".
- `parse` reads a leading "[...]"; if its text is one of the known labels, that is the category
  and the rest (trimmed) is the description. Anything else - no prefix, an unknown label, legacy or
  seeded text - is category "Other" with the WHOLE stored text as the description.
"""
import re
from enum import StrEnum
from typing import Tuple


class ProblemCategory(StrEnum):
    DEVICE_NOT_WORKING = "Device not working"
    ABNORMAL_READING = "Abnormal reading"
    PHYSICAL_DAMAGE = "Physical damage"
    ALARM_PROBLEM = "Alarm/problem"
    POWER_ISSUE = "Power issue"
    OTHER = "Other"


# Same expression as the mobile app: r'^\[(.+?)\]\s*([\s\S]*)$'
_PREFIX = re.compile(r"^\[(.+?)\]\s*([\s\S]*)$")
_BY_LABEL = {c.value: c for c in ProblemCategory}


def compose(category: ProblemCategory, description: str) -> str:
    return f"[{ProblemCategory(category).value}] {description.strip()}"


def parse(stored: str) -> Tuple[ProblemCategory, str]:
    text = (stored or "").strip()
    match = _PREFIX.match(text)
    if match is not None:
        category = _BY_LABEL.get(match.group(1))
        if category is not None:
            return category, match.group(2).strip()
    return ProblemCategory.OTHER, text
