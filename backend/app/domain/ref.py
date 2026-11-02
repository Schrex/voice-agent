"""Request refs as rendered on the dashboard and spoken on calls: "R-1042". Pure."""

import re

_REF = re.compile(r"^R-(\d{1,18})$")


def parse_ref(ref: str) -> int | None:
    """ "R-1042" → 1042; anything else → None."""
    match = _REF.match(ref)
    return None if match is None else int(match.group(1))
