from datetime import datetime, timedelta
import re
from typing import Optional, Tuple
import pytz


class DateTimeParser:
    """Resolves natural language date and time expressions to timezone-aware datetimes."""

    WEEKDAYS = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }

    @classmethod
    def resolve_datetime(
        cls,
        text: str,
        user_tz: str = "UTC",
        ref_time: Optional[datetime] = None,
    ) -> Tuple[Optional[datetime], bool, Optional[str]]:
        """
        Parses text for date/time references relative to ref_time and user_tz.
        Returns (resolved_datetime, requires_clarification, clarification_prompt).
        """
        try:
            tz = pytz.timezone(user_tz)
        except Exception:
            tz = pytz.UTC

        now = ref_time if ref_time else datetime.now(tz)
        if now.tzinfo is None:
            now = tz.localize(now)

        lower = text.lower()

        # Handle 'before' offsets: e.g. "remind 5 mins before 11:45" or "5 mins before the time"
        before_offset_mins = 0
        before_match = re.search(r"(\d+)\s*(?:min|mins|minute|minutes)\s+before", lower)
        if before_match:
            before_offset_mins = int(before_match.group(1))

        # 1. "in X minutes/hours/days"
        duration_min_match = re.search(r"in\s+(\d+)\s*(?:min|mins|minute|minutes)", lower)
        if duration_min_match:
            mins = int(duration_min_match.group(1))
            return now + timedelta(minutes=mins), False, None

        duration_hr_match = re.search(r"in\s+(\d+)\s*(?:hr|hrs|hour|hours)", lower)
        if duration_hr_match:
            hrs = int(duration_hr_match.group(1))
            return now + timedelta(hours=hrs), False, None

        # 2. "Friday evening" without specific hour -> clarify
        if "evening" in lower and not any(h in lower for h in ["pm", "am", "at "]):
            return None, True, "What time in the evening would you prefer (e.g. 6 PM or 7 PM)?"

        if "morning" in lower and not any(h in lower for h in ["pm", "am", "at "]):
            return None, True, "What time in the morning would you prefer (e.g. 8 AM or 9 AM)?"

        # 3. Time extraction (e.g., "at 11:45", "at 8 AM", "at 4 PM", "at 7", "11:45")
        hour = 9
        minute = 0
        has_time = False

        # First match explicit HH:MM (e.g. 11:45 or 11:45 am)
        hh_mm_match = re.search(r"\b(\d{1,2}):(\d{2})\s*(am|pm)?\b", lower)
        # Then match HH am/pm (e.g. 8 am, 6 pm)
        hh_ampm_match = re.search(r"\b(\d{1,2})\s*(am|pm)\b", lower)
        # Then match "at HH" (e.g. at 7)
        at_hh_match = re.search(r"at\s+(\d{1,2})\b", lower)

        if hh_mm_match:
            has_time = True
            h = int(hh_mm_match.group(1))
            m = int(hh_mm_match.group(2))
            meridiem = hh_mm_match.group(3)
            if meridiem:
                if meridiem == "pm" and h < 12:
                    h += 12
                elif meridiem == "am" and h == 12:
                    h = 0
            elif "evening" in lower and h < 12:
                h += 12
            hour = h
            minute = m
        elif hh_ampm_match:
            has_time = True
            h = int(hh_ampm_match.group(1))
            meridiem = hh_ampm_match.group(2)
            if meridiem == "pm" and h < 12:
                h += 12
            elif meridiem == "am" and h == 12:
                h = 0
            hour = h
            minute = 0
        elif at_hh_match:
            has_time = True
            h = int(at_hh_match.group(1))
            if "evening" in lower and h < 12:
                h += 12
            hour = h
            minute = 0

        # 4. Target date calculation
        target_date = now.date()
        explicit_date = cls._extract_calendar_date(lower, now)

        if explicit_date is not None:
            target_date = explicit_date
        elif "day after tomorrow" in lower:
            target_date = now.date() + timedelta(days=2)
        elif "tomorrow" in lower:
            target_date = now.date() + timedelta(days=1)
        elif "today" in lower or "tonight" in lower:
            target_date = now.date()
        elif "next week" in lower:
            target_date = now.date() + timedelta(days=7)
        else:
            # Check for weekday names (e.g., "next monday", "on friday")
            for day_name, day_idx in cls.WEEKDAYS.items():
                if day_name in lower:
                    days_ahead = (day_idx - now.weekday()) % 7
                    if days_ahead == 0 and not has_time:
                        days_ahead = 7
                    elif days_ahead == 0 and has_time:
                        candidate_time = tz.localize(datetime(now.year, now.month, now.day, hour, minute))
                        if candidate_time <= now:
                            days_ahead = 7
                    target_date = now.date() + timedelta(days=days_ahead)
                    break

        resolved = tz.localize(datetime(target_date.year, target_date.month, target_date.day, hour, minute))

        # Apply offset if 'X minutes before' was requested
        if before_offset_mins > 0:
            resolved = resolved - timedelta(minutes=before_offset_mins)

        # If time is in the past for today, bump to tomorrow if no explicit day was specified
        if (
            resolved < now
            and explicit_date is None
            and "today" not in lower
            and "tomorrow" not in lower
        ):
            resolved = resolved + timedelta(days=1)

        return resolved, False, None

    MONTHS = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }

    @classmethod
    def _extract_calendar_date(cls, lower: str, now: datetime):
        """Parses '22 December', 'Dec 22nd', '22/12' or '22-12-2026'. Rolls past dates to next year."""
        month_pattern = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
        day = month = year = None

        m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{month_pattern}(?:\s+(\d{{4}}))?", lower)
        if m:
            day, month = int(m.group(1)), cls.MONTHS[m.group(2)]
            year = int(m.group(3)) if m.group(3) else None
        else:
            m = re.search(rf"\b{month_pattern}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?", lower)
            if m:
                month, day = cls.MONTHS[m.group(1)], int(m.group(2))
                year = int(m.group(3)) if m.group(3) else None
            else:
                m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", lower)
                if m:
                    day, month = int(m.group(1)), int(m.group(2))
                    if m.group(3):
                        year = int(m.group(3))
                        if year < 100:
                            year += 2000

        if day is None or month is None:
            return None
        try:
            candidate = datetime(year or now.year, month, day).date()
        except ValueError:
            return None
        if year is None and candidate < now.date():
            try:
                candidate = datetime(now.year + 1, month, day).date()
            except ValueError:
                return None
        return candidate
