# -*- coding: utf-8 -*-
"""The SIP phone container module for DoorPi.

A SIP phone module is required for DoorPi to make any outgoing calls
due to events (like a bell being rang), or to accept incoming calls.

The following requirements apply to all SIP phone modules:

- The module must be located at ``doorpi.sipphone.from_{name}``, where
  ``{name}`` is the name of the module. That same name is used in the
  configuration file to select the module.
- The top-level module must provide a function called ``instantiate()``,
  which takes no arguments and returns an instance of the phone module's
  base class.
- The phone module's base class must implement all instance methods of
  ``AbstractSIPPhone``. It is recommended that it inherits from the
  latter, however this is not a hard requirement.

A proper SIP phone module will fire these events during its life cycle:

- OnSIPPhoneCreate, OnSIPPhoneStart, OnSIPPhoneDestroy:
  These publish the module life cycle. They are fired by the abstract
  base class' respective methods, and are registered during its
  ``__init__()`` and unregistered during its ``__del__()``. All other
  events mentioned here must be registered and fired manually.
- OnCallOutgoing:
  Fired when a call is started.
  Arguments:
    - "uri": The callee's URI as given (not canonicalized)
    - "canonical_uri": The callee's URI (canonicalized)
- OnCallConnect, OnCallDisconnect:
  Fired when a call is connected (picked up by remote) or disconnected
  (remote hung up), respectively.
  Arguments:
    - "uri": The remote end's URI
- OnCallIncoming:
  Fired when an external call comes in. This event is fired
  regardless of whether the call is accepted, rejected, or
  another call is already active.
  Arguments:
    - "uri": The caller's URI
- OnCallAccepted:
  Fired when an incoming call is being accepted.
  Arguments:
    - "uri": The caller's URI
- OnCallReject, OnCallBusy:
  Fired when an incoming call rejected due to the caller's URI
  not being a registered administrator or another call being
  currently active, respectively.
  Arguments:
    - "uri": The caller's URI
- OnDTMF_<seq>:
  Fired when the DTMF sequence ``<seq>`` was received.
"""

import importlib
import logging

import doorpi

SIPPHONE_SECTION = 'SIP-Phone'
logger = logging.getLogger(__name__)
logger.debug("%s loaded", __name__)


def load():
    sipphone_name = doorpi.DoorPi().config.get("SIP-Phone", "type", "dummy")
    try:
        return importlib.import_module(f"doorpi.sipphone.from_{sipphone_name}").instantiate()
    except ImportError as err:
        raise RuntimeError(f"Failed to load sip phone module {sipphone_name}") from err
