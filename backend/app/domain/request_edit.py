"""What a coordinator's edit of a Request changes (ticket #31). Pure: no I/O."""

from collections.abc import Mapping


def changed_fields(
    current: Mapping[str, object], proposed: Mapping[str, object]
) -> tuple[dict[str, object], dict[str, object]]:
    """`(before, after)` of the proposed fields whose value differs from the current one.

    Both are empty when the edit changes nothing. A proposed field missing from `current` is not
    editable and raises KeyError.
    """
    changed = [name for name, value in proposed.items() if current[name] != value]
    return {n: current[n] for n in changed}, {n: proposed[n] for n in changed}
