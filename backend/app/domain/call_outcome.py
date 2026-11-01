"""Call outcome after the call ends (architecture §3.4, §5 `calls.outcome`). Pure: no I/O.

Outcomes this module sets so far: `rejected`, `transferred`, `submitted`, `none`. `draft`
(#28), `emergency` (#26) and `status_only` (#16) come with the tickets that create them.
"""

from collections.abc import Collection

# The ElevenLabs system tool the agent uses to put the Foreman through to the office
# (architecture §3.3, step 2). It appears as a tool call in the post-call transcript.
TRANSFER_TOOL = "transfer_to_number"


def call_outcome(*, rejected: bool, submitted: bool, tools_called: Collection[str]) -> str:
    """`rejected` (unrostered caller) > `transferred` > `submitted` > `none`.

    `submitted` means a Request was actually recorded on the call, not that the agent tried.
    A transfer outranks a submission because the office then also spoke with the Foreman.
    """
    if rejected:
        return "rejected"
    if TRANSFER_TOOL in tools_called:
        return "transferred"
    if submitted:
        return "submitted"
    return "none"
