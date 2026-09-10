"""Event loop selection.

psycopg's async mode cannot run on Windows' default ProactorEventLoop and
raises InterfaceError on the first connection. The selector loop works, so on
Windows the policy is switched before any loop is created.

This is a no-op everywhere else, including inside the container, so the same
entry points work on a developer's Windows machine and in production Linux
without branching at the call site.

Import and call this before `asyncio.run` or before uvicorn starts a loop.
"""

from __future__ import annotations

import asyncio
import sys


def configure_event_loop() -> None:
    """Select an event loop policy the database driver can actually use."""
    if sys.platform != "win32":
        return

    selector_policy = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if selector_policy is None:  # pragma: no cover - non-Windows builds
        return

    current = asyncio.get_event_loop_policy()
    if isinstance(current, selector_policy):
        return

    asyncio.set_event_loop_policy(selector_policy())
