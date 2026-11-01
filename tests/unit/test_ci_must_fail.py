def test_deliberately_fails_to_prove_ci_goes_red() -> None:
    """Temporary (#1 DoD): proves a failing test turns CI red. Reverted before merge."""
    raise AssertionError("deliberate failure")
