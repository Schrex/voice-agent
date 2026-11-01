"""Call outcome after the call ends (architecture §3.4, §5 `calls.outcome`). Pure: no I/O.

Outcomes: `rejected`, `emergency` (#26), `transferred`, `submitted`, `draft`, `status_only`,
`none`.
"""

from collections.abc import Collection

# The ElevenLabs system tool the agent uses to put the Foreman through to the office
# (architecture §3.3, step 2). It appears as a tool call in the post-call transcript.
TRANSFER_TOOL = "transfer_to_number"


def call_outcome(
    *,
    rejected: bool,
    submitted: bool,
    tools_called: Collection[str],
    drafted: bool = False,
    looked_up: bool = False,
    emergency: bool = False,
) -> str:
    """`rejected` (unrostered caller) > `emergency` > `transferred` > `submitted` > `draft`
    > `status_only` > `none`.

    `submitted` means a Request was actually recorded on the call, not that the agent tried.
    `drafted` means a Draft was saved from the call analysis (only when nothing was submitted).
    `looked_up` means the status lookup returned at least one of the Foreman's Requests; the
    call is `status_only` when nothing else happened on it.
    A transfer outranks both because the office then also spoke with the Foreman.
    `emergency` means an Emergency Request was recorded on the call; it outranks the transfer
    and the Request that every Emergency also has (ticket #26).
    """
    if rejected:
        return "rejected"
    if emergency:
        return "emergency"
    if TRANSFER_TOOL in tools_called:
        return "transferred"
    if submitted:
        return "submitted"
    if drafted:
        return "draft"
    if looked_up:
        return "status_only"
    return "none"
