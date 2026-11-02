"""End-of-day summary email to Coordinators (ticket #23; spec J1 step 8, J9; architecture §6).

Postmark is replaced by a fake `EmailSender`; the alerts table records what was sent (or why
not), one `eod_summary` alert per Coordinator per New York day, so a restart never resends.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import partial
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Alert, Foreman, Job, Request, Staff
from app.integrations.postmark import EmailNotSent
from app.jobs import end_of_day_summary_tick
from app.services.eod_summary import send_end_of_day_summary
from app.services.roster import load_roster_file, seed_roster

SAMPLE_ROSTER = Path(__file__).resolve().parents[2] / "backend" / "seed" / "sample_roster.json"

# Mon, Nov 2, 2026 (EST): 5:00 PM New York = 22:00 UTC.
FIVE_PM = datetime(2026, 11, 2, 22, 0, tzinfo=UTC)
# Sun, Nov 1, 5:00 PM EST: the start of Monday's window.
WINDOW_START = datetime(2026, 11, 1, 22, 0, tzinfo=UTC)


@dataclass
class FakeEmail:
    sent: list[tuple[str, str, str]] = field(default_factory=list)
    fail: bool = False

    def send(self, to: str, subject: str, text_body: str) -> str:
        if self.fail:
            raise EmailNotSent("Postmark answered 422")
        self.sent.append((to, subject, text_body))
        return f"msg-{len(self.sent)}"


@pytest.fixture
def email() -> FakeEmail:
    return FakeEmail()


@pytest.fixture
def roster(db_session: Session) -> Session:
    seed_roster(db_session, load_roster_file(SAMPLE_ROSTER))
    return db_session


def _staff(session: Session, name: str, email: str) -> Staff:
    staff = Staff(id=uuid.uuid4(), name=name, email=email)
    session.add(staff)
    session.flush()
    return staff


def _add(
    session: Session,
    need: str,
    *,
    urgency: str | None = "Planned",
    status: str = "Recorded",
    recorded_at: datetime | None = FIVE_PM - timedelta(hours=3),
) -> Request:
    request = Request(
        foreman_id=session.scalars(select(Foreman.id).where(Foreman.first_name == "Dale")).one(),
        job_id=session.scalars(select(Job.id).where(Job.name == "Route 104 Widening")).one(),
        job_spoken="the 104 job",
        category="Trucking",
        need=need,
        quantity=Decimal("3"),
        unit="trucks",
        needed_by_spoken="Tuesday at seven",
        needed_by=datetime(2026, 11, 3, 12, 0, tzinfo=UTC),
        urgency=urgency,
        status=status,
        source="ai_call",
        recorded_at=recorded_at,
    )
    if status == "Resolved":
        request.outcome, request.explanation = "Fulfilled", "Sent"
        request.resolved_at = FIVE_PM - timedelta(hours=1)
    session.add(request)
    session.flush()
    return request


def _fixed(at: datetime) -> datetime:
    return at


def _alerts(session: Session) -> list[Alert]:
    query = select(Alert).where(Alert.kind == "eod_summary").order_by(Alert.id)
    return list(session.scalars(query))


def test_at_five_pm_each_coordinator_gets_the_new_planned_requests_and_open_counts(
    roster: Session, email: FakeEmail
) -> None:
    pat = _staff(roster, "Pat Lee", "pat@example.com")
    sam = _staff(roster, "Sam Ortiz", "sam@example.com")
    planned = _add(roster, "tri-axle dump trucks")
    _add(roster, "a mini excavator", urgency="Today", status="Acknowledged")
    _add(roster, "stone", status="In Progress", recorded_at=WINDOW_START - timedelta(minutes=1))

    send_end_of_day_summary(roster, email, now=FIVE_PM)

    assert sorted(to for to, _, _ in email.sent) == ["pat@example.com", "sam@example.com"]
    _, subject, body = email.sent[0]
    assert subject == "End-of-day summary, Mon, Nov 2"
    assert body == (
        "End-of-day summary, Mon, Nov 2\n"
        "\n"
        "New Planned requests since Sun, Nov 1, 5:00 PM: 1\n"
        f"- {planned.ref_display} from Dale Kramer, Route 104 Widening: tri-axle dump trucks, "
        "3 trucks, needed by Tue, Nov 3, 7:00 AM (Recorded)\n"
        "\n"
        "Open requests: 3\n"
        "- Recorded: 1\n"
        "- Acknowledged: 1\n"
        "- In Progress: 1\n"
    )
    alerts = _alerts(roster)
    assert {a.to_staff_id for a in alerts} == {pat.id, sam.id}
    assert all(a.channel == "email" and a.status == "sent" for a in alerts)
    assert all(a.provider_id is not None and a.sent_at == FIVE_PM for a in alerts)


def test_lists_only_planned_requests_recorded_since_the_previous_five_pm(
    roster: Session, email: FakeEmail
) -> None:
    _staff(roster, "Pat Lee", "pat@example.com")
    _add(roster, "before the window", recorded_at=WINDOW_START)
    _add(roster, "first in the window", recorded_at=WINDOW_START + timedelta(seconds=1))
    _add(roster, "at five", recorded_at=FIVE_PM)
    _add(roster, "a Today request", urgency="Today")
    _add(roster, "a Draft", status="Draft", recorded_at=None)
    _add(roster, "already resolved", status="Resolved")

    send_end_of_day_summary(roster, email, now=FIVE_PM)

    [(_, _, body)] = email.sent
    assert "New Planned requests since Sun, Nov 1, 5:00 PM: 3\n" in body
    assert "first in the window" in body
    assert "at five" in body
    assert "already resolved" in body and "(Resolved)" in body
    for absent in ("before the window", "a Today request", "a Draft"):
        assert absent not in body


def test_a_planned_request_recorded_after_five_pm_waits_for_the_next_summary(
    roster: Session, email: FakeEmail
) -> None:
    _staff(roster, "Pat Lee", "pat@example.com")
    _add(roster, "late call", recorded_at=FIVE_PM + timedelta(minutes=10))

    send_end_of_day_summary(roster, email, now=FIVE_PM + timedelta(minutes=30))
    send_end_of_day_summary(roster, email, now=FIVE_PM + timedelta(days=1))

    first, second = (body for _, _, body in email.sent)
    assert "late call" not in first
    assert "late call" in second


def test_nothing_is_sent_before_five_pm(roster: Session, email: FakeEmail) -> None:
    _staff(roster, "Pat Lee", "pat@example.com")

    send_end_of_day_summary(roster, email, now=FIVE_PM - timedelta(seconds=1))

    assert email.sent == []
    assert _alerts(roster) == []


def test_runs_once_per_day_across_restarts(roster: Session, email: FakeEmail) -> None:
    _staff(roster, "Pat Lee", "pat@example.com")
    _add(roster, "tri-axle dump trucks")

    # Each tick is a fresh call with nothing in memory, as after a restart.
    for minutes in (0, 1, 2, 60, 6 * 60 + 59):
        send_end_of_day_summary(roster, email, now=FIVE_PM + timedelta(minutes=minutes))

    assert len(email.sent) == 1
    assert len(_alerts(roster)) == 1

    send_end_of_day_summary(roster, email, now=FIVE_PM + timedelta(days=1))
    assert len(email.sent) == 2


def test_a_restart_after_five_pm_still_sends_that_days_summary(
    roster: Session, email: FakeEmail
) -> None:
    _staff(roster, "Pat Lee", "pat@example.com")

    send_end_of_day_summary(roster, email, now=FIVE_PM + timedelta(hours=2))

    assert [subject for _, subject, _ in email.sent] == ["End-of-day summary, Mon, Nov 2"]


def test_every_staff_member_gets_it(roster: Session, email: FakeEmail) -> None:
    """One Staff role (ADR 0006): everyone on the staff list is a Coordinator."""
    _staff(roster, "Pat Lee", "pat@example.com")
    _staff(roster, "Alex Admin", "alex@example.com")

    send_end_of_day_summary(roster, email, now=FIVE_PM)

    assert sorted(to for to, _, _ in email.sent) == ["alex@example.com", "pat@example.com"]


def test_a_provider_error_is_a_failed_alert_and_is_not_retried(
    roster: Session, email: FakeEmail
) -> None:
    _staff(roster, "Pat Lee", "pat@example.com")
    email.fail = True

    send_end_of_day_summary(roster, email, now=FIVE_PM)
    email.fail = False
    send_end_of_day_summary(roster, email, now=FIVE_PM + timedelta(minutes=1))

    assert email.sent == []
    [alert] = _alerts(roster)
    assert alert.status == "failed"
    assert alert.detail == "Email not sent: Postmark answered 422"


def test_the_scheduled_tick_opens_its_own_session_and_sends_once(
    roster: Session, email: FakeEmail
) -> None:
    _staff(roster, "Pat Lee", "pat@example.com")

    for at in (FIVE_PM, FIVE_PM + timedelta(minutes=1)):
        end_of_day_summary_tick(lambda: roster, lambda: email, partial(_fixed, at))

    assert len(email.sent) == 1


def test_a_removed_person_gets_no_summary(roster: Session, email: FakeEmail) -> None:
    _staff(roster, "Pat Lee", "pat@example.com")
    gone = _staff(roster, "Alex Gone", "alex@example.com")
    gone.removed_at = FIVE_PM - timedelta(days=1)
    roster.flush()

    send_end_of_day_summary(roster, email, now=FIVE_PM)

    assert [to for to, _, _ in email.sent] == ["pat@example.com"]
