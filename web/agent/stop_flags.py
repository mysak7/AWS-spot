"""Per-session stop flags — lets the web layer signal a running agent to halt."""
from threading import Event

_flags: dict[str, Event] = {}


def create_flag(session_id: str) -> Event:
    e = Event()
    _flags[session_id] = e
    return e


def request_stop(session_id: str) -> bool:
    """Set the stop flag. Returns True if the session was found."""
    e = _flags.get(session_id)
    if e:
        e.set()
        return True
    return False


def cleanup(session_id: str) -> None:
    _flags.pop(session_id, None)
