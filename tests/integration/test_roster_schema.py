import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Foreman, ForemanPhone


def test_phone_number_is_unique_across_all_foremen(db_session: Session) -> None:
    dale = Foreman(first_name="Dale", last_name="Kramer")
    rita = Foreman(first_name="Rita", last_name="Owens")
    db_session.add_all([dale, rita])
    db_session.add(ForemanPhone(foreman=dale, e164="+15855550101"))
    db_session.flush()

    db_session.add(ForemanPhone(foreman=rita, e164="+15855550101"))
    with pytest.raises(IntegrityError, match="uq_foreman_phones_e164"):
        db_session.flush()


def test_a_foreman_may_have_several_numbers(db_session: Session) -> None:
    dale = Foreman(first_name="Dale", last_name="Kramer")
    db_session.add_all(
        [
            ForemanPhone(foreman=dale, e164="+15855550101"),
            ForemanPhone(foreman=dale, e164="+15855550102"),
        ]
    )
    db_session.flush()

    assert len(dale.phones) == 2


def test_phone_number_must_be_e164(db_session: Session) -> None:
    dale = Foreman(first_name="Dale", last_name="Kramer")
    db_session.add(ForemanPhone(foreman=dale, e164="585-555-0101"))
    with pytest.raises(IntegrityError, match="ck_foreman_phones_e164_format"):
        db_session.flush()
