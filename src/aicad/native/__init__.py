"""Formwright native file formats (.fwpart, .fwasm, .fwdrw, .fwprog): the full parametric model in one file, so work
moves between workspaces without feature recognition. Specification: docs/FORMATS.md.

- ``container``  deterministic zip writer, untrusted-input reader (caps, zip-bomb and path guards, sha256 of every
                 entry, manifest schema, format versions and migrations), per-workspace HMAC signature.
- ``gate``       static checks of every Python file in a package before anything runs (the runner tripwire, plus a
                 strict allow-list for files from another workspace).
- ``part``       build a .fwpart from a project workspace; install one into a fresh workspace; compare geometry.
- ``bundles``    .fwasm / .fwdrw / .fwprog documents (assembly, drawing, program) around embedded parts.
"""

from __future__ import annotations


class NativeFormatError(Exception):
    """A package that cannot be read or is not allowed (shown to the user as is: plain language, no internals)."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status
