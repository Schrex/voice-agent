from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


def db_reachable(session: Session) -> bool:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True
