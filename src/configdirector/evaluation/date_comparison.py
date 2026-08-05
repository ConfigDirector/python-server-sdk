from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

__all__ = ["compare_date"]

# The ECMAScript Date Time String Format, which is what `new Date(string)` accepts and what the
# ConfigDirector dashboard emits. Anything outside it is treated as an unparseable date.
_ISO = re.compile(
    r"""^
    (?P<year>[+-]\d{6}|\d{4})
    (?:-(?P<month>\d{2})
      (?:-(?P<day>\d{2}))?
    )?
    (?:[T](?P<hour>\d{2}):(?P<minute>\d{2})
      (?::(?P<second>\d{2})
        (?:\.(?P<fraction>\d{1,}))?
      )?
      (?P<offset>[Zz]|[+-]\d{2}:\d{2})?
    )?
    $""",
    re.VERBOSE,
)


def compare_date(value: str, operator: str, target_values: list[str]) -> bool:
    if not target_values:
        return False

    parsed_value = _parse_date(value)
    parsed_target = _parse_date(target_values[0])
    if parsed_value is None or parsed_target is None:
        return False

    match operator:
        case "is after":
            return parsed_value > parsed_target
        case "is before":
            return parsed_value < parsed_target
        case _:
            return False


def _parse_date(value: str) -> datetime | None:
    match = _ISO.match(value)
    if match is None:
        return None

    offset = match.group("offset")

    # A value with no offset is treated as UTC
    if offset and offset not in ("Z", "z"):
        sign = -1 if offset[0] == "-" else 1
        hours, minutes = int(offset[1:3]), int(offset[4:6])
        tzinfo = timezone(sign * timedelta(hours=hours, minutes=minutes))
    else:
        tzinfo = timezone.utc

    fraction = match.group("fraction") or ""
    try:
        parsed = datetime(
            year=int(match.group("year")),
            month=int(match.group("month") or 1),
            day=int(match.group("day") or 1),
            hour=int(match.group("hour") or 0),
            minute=int(match.group("minute") or 0),
            second=int(match.group("second") or 0),
            # Precision is milliseconds; finer digits are truncated.
            microsecond=int(fraction[:3].ljust(3, "0")) * 1000 if fraction else 0,
            tzinfo=tzinfo,
        )
    except ValueError:
        # Out-of-range components, such as month 13 or day 32.
        return None

    return parsed
