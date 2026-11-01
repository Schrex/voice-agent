def test_deliberately_fails_to_prove_ci_goes_red() -> None:
    """Temporary (#1 DoD): proves a failing test turns CI red. Reverted in the next commit."""
    assert False, "deliberate failure"
