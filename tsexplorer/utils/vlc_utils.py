from ..extern.vlc import vlc
from typing import Callable

# The 'event_attach' returns 0 on success, ENOMEM on failure
VLC_ATTACH_SUCCESS: int = 0


class EventBlocker:
    '''
    Simple context manager for blocking certain events for a short time period
    '''
    def __init__(
            self, event_mngr: vlc.EventManager, event_type: vlc.EventType,
            cb: Callable
            ):
        '''
        Parameters
        ----------
        event_mngr: vlc.EventManager
            The event manager used for the events.
        event_type: vlc.EventType
            The type of the event that should be blocked
        cb: Callable
            The callback registered for the given event.
        '''
        self._event_mngr = event_mngr
        self._event_type = event_type
        self._cb = cb

    def __enter__(self):
        ''' Detach the event handler from the manager '''
        self._event_mngr.event_detach(
                self._event_type
        )

    def __exit__(self, exc_type, exc_val, exc_tb):
        ''' Reattach the event handler for the given manager'''
        out = self._event_mngr.event_attach(
                self._event_type,
                self._cb
        )
        if out != VLC_ATTACH_SUCCESS:
            raise RuntimeError(("Could not re-attach event for "
                                f"{self._event_type}"))
