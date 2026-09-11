"""Hard process-death injection used only by crash-consistency tests."""

import os


def maybe_crash(point: str) -> None:
    """Terminate immediately when the configured crash point is reached."""
    if os.environ.get("TANDEM_CRASH_POINT") == point:
        os._exit(86)
