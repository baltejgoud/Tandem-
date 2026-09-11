"""Statutory and business-day deadline service for Regulation E disputes."""

from datetime import datetime, time, timedelta, timezone
from typing import Dict, Optional


def add_business_days(start_date: datetime, business_days: int) -> datetime:
    """Add business days to a timestamp, skipping Saturdays and Sundays.

    Sets deadline cutoff time to 17:00:00 (5:00 PM) on the final business day.
    """
    current = start_date
    added = 0
    while added < business_days:
        current += timedelta(days=1)
        # weekday: 0=Monday, ..., 4=Friday, 5=Saturday, 6=Sunday
        if current.weekday() < 5:
            added += 1

    # Return with 17:00:00 cutoff time in UTC
    return datetime.combine(current.date(), time(hour=17, minute=0, second=0), tzinfo=timezone.utc)


def calculate_reg_e_deadlines(
    opened_at: Optional[datetime] = None,
) -> Dict[str, datetime]:
    """Calculate statutory deadlines under 12 CFR 1005.11.

    - 2-day Notice: 2 business days after provisional credit
    - 10-day Investigation/Credit: 10 business days from dispute receipt
    - 45-day Final Resolution: 45 calendar days from dispute receipt
    """
    base = opened_at or datetime.now(timezone.utc)

    notice_deadline = add_business_days(base, 2)
    investigation_deadline = add_business_days(base, 10)
    final_resolution_deadline = base + timedelta(days=45)

    return {
        "NOTICE_2_DAY": notice_deadline,
        "INVESTIGATION_10_DAY": investigation_deadline,
        "FINAL_RESOLUTION_45_DAY": final_resolution_deadline,
    }
