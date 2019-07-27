"""The PJSUA2 SIP phone module for DoorPi."""

from doorpi import DoorPi

import logging

EVENT_SOURCE = __name__
logger = logging.getLogger(__name__)


def instantiate():
    from .glue import Pjsua2
    return Pjsua2()


def fire_event(event_name, async_only=False, *, remote_uri=None):
    """Helper function to ease firing events.

    Normally all DoorPi events are fired asynchronously, however this
    causes many short-lived event threads to appear. If one of these
    event threads calls into PJSUA2, it will permanently register the
    thread, effectively leaking memory over its life time.

    That is why events used internally by this module also fire a
    synchronous version, whose name is suffixed with "_S".
    """
    eh = DoorPi().event_handler
    kwargs = {"remote_uri": remote_uri} if remote_uri is not None else {}

    eh.fire_event_asynchron(event_name, EVENT_SOURCE, kwargs=kwargs)
    if not async_only:
        eh.fire_event_synchron(f"{event_name}_S", EVENT_SOURCE, kwargs=kwargs)
