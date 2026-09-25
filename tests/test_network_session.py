"""Test _NetworkSession.expired() handles both naive and aware datetimes."""

from datetime import UTC, datetime, timedelta

from CasambiBt._network import _NetworkSession


def _make_session(expires: datetime) -> _NetworkSession:
    return _NetworkSession(
        session="session",
        network="network",
        manager=True,
        keyID=1,
        expires=expires,
    )


def test_expired_with_naive_datetime() -> None:
    """A regular, freshly-created session compares fine using naive datetimes."""
    assert _make_session(datetime.utcnow() - timedelta(days=1)).expired()
    assert not _make_session(datetime.utcnow() + timedelta(days=1)).expired()


def test_expired_with_timezone_aware_datetime() -> None:
    """A cached session with a timezone-aware `expires` must not raise.

    This can happen if session.pck was written by an incompatible source;
    the comparison must still be evaluated correctly rather than crashing
    with "can't compare offset-naive and offset-aware datetimes".
    """
    assert _make_session(datetime.now(UTC) - timedelta(days=1)).expired()
    assert not _make_session(datetime.now(UTC) + timedelta(days=1)).expired()
