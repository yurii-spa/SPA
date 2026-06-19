"""SPA version info.

This module is the single source of truth for SPA's version number.
All other modules should import VERSION from here rather than hardcoding it.
"""

VERSION: str = "10.0.0"
VERSION_TUPLE: tuple = (10, 0, 0)
RELEASE_DATE: str = "2026-06-19"
BUILD_SPRINTS: str = "v9.21-v9.99"  # sprints included in this release

__all__ = ["VERSION", "VERSION_TUPLE", "RELEASE_DATE", "BUILD_SPRINTS"]
