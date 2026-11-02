"""Optimistic revision checks, required before accepting sheet edits."""


class RevisionConflict(ValueError):
    """A staged edit no longer has the current base revision."""


def check_revision(expected: int, actual: int) -> None:
    if expected != actual:
        raise RevisionConflict(f"Base revision {expected} differs from current revision {actual}")
