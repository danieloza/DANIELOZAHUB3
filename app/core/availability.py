from datetime import datetime, date, time
import holidays

class SalonAvailability:
    def __init__(self):
        # Initialize Polish holidays
        self.pl_holidays = holidays.Poland()

    def is_working_day(self, check_date: date) -> bool:
        """Check if salon is open on a given date (No Sundays, No Holidays)."""
        if check_date.weekday() == 6:  # Sunday
            return False
        if check_date in self.pl_holidays:
            return False
        return True

    def get_working_hours(self, check_date: date) -> tuple[time, time] | None:
        """Returns (start, end) times for a given date or None if closed."""
        if not self.is_working_day(check_date):
            return None
            
        if check_date.weekday() == 5:  # Saturday
            return time(9, 0), time(15, 0)
            
        # Monday - Friday
        return time(9, 0), time(19, 0)

    def is_time_allowed(self, check_dt: datetime) -> bool:
        """Full check if salon is open at specific datetime."""
        hours = self.get_working_hours(check_dt.date())
        if not hours:
            return False
            
        start, end = hours
        return start <= check_dt.time() < end

availability = SalonAvailability()
