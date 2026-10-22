"""These integration checks may change Windows credentials and scheduled tasks."""
import os
import sys


def require_disposable_windows():
    if sys.platform != "win32" or os.environ.get("NC_WINDOWS_TESTS_DISPOSABLE") != "1":
        raise SystemExit(
            "Run Windows integration checks only on a disposable Windows runner "
            "with NC_WINDOWS_TESTS_DISPOSABLE=1 (the checked-in workflow sets this)."
        )
