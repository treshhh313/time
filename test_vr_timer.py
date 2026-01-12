import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Mock customtkinter and pyttsx3 BEFORE importing vr_timer
sys.modules["customtkinter"] = MagicMock()
sys.modules["pyttsx3"] = MagicMock()

# Add current dir to path to import vr_timer
sys.path.append(os.getcwd())

from vr_timer import TimerThread

class TestTimerLogic(unittest.TestCase):
    def test_timer_math(self):
        mins = 1
        total = mins * 60
        # TimerThread logic is: total_seconds = int(duration_minutes * 60)
        t = TimerThread(mins, None, None, None)
        self.assertEqual(t.total_seconds, 60)
        self.assertEqual(t.remaining_seconds, 60)

    def test_timer_add_time(self):
        t = TimerThread(10, None, None, None)
        # 600 seconds
        t.remaining_seconds = 600
        t.add_time(5)
        self.assertEqual(t.remaining_seconds, 600 + 300)
        # Total seconds should update if remaining > total
        self.assertEqual(t.total_seconds, 900)

if __name__ == "__main__":
    unittest.main()
