"""
Standalone test for sheets_logger.py -- appends one test row to your real
sheet. First run will open a browser window asking you to log in and
approve access; every run after that is silent.

    python auto-apply/sheets_logger_test.py
"""
import sys
import os
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
from sheets_logger import append_application_row


def main():
    today = date.today()
    date_str = f"{today.month}/{today.day}/{today.year}"  # avoids Windows-incompatible %-m/%-d strftime flags

    result = append_application_row(
        date_str,
        "TEST ROW -- delete me",
        "Test Company",
        "This is a test row from sheets_logger_test.py, safe to delete.",
    )
    print("Appended successfully.")
    print(f"Updated range: {result.get('updates', {}).get('updatedRange')}")


if __name__ == "__main__":
    main()
