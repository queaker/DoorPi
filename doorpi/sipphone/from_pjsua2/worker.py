import logging
import pjsua2 as pj
import threading
import time

from doorpi import DoorPi
from doorpi.sipphone import SIPPHONE_SECTION

from . import fire_event, logger
from .callbacks import AccountCallback, CallCallback
from .config import Config
from .fileio import DialTonePlayer, CallRecorder


class Worker():
    def __init__(self, sipphone):
        self.__phone = sipphone
        self.__ep = None

        conf = DoorPi().config
        self.__call_timeout = conf.get_int(SIPPHONE_SECTION, "call_timeout", 15)
        self.__max_call_time = conf.get_int(SIPPHONE_SECTION, "max_call_time", 120)

        self.running = True
        self.error = None
        self.ready = threading.Semaphore(0)
        self.wake = threading.Condition()
        self.hangup = 0

    def __call__(self):
        try: self.pjInit()
        except Exception as ex:
            self.error = ex
            return
        finally:
            self.ready.release()

        try:
            while self.running:
                self.handleNativeEvents()
                self.checkHangupAll()
                self.checkCallTime()
                self.createCalls()
                with self.wake: self.wake.wait(0.05)
        except Exception as ex:
            self.error = ex
            return
        finally:
            self.ready.release()

    def __del__(self):
        self.running = False
        with self.wake: self.wake.notify()
        self.ready.acquire()
        self.__ep.libDestroy()

    def pjInit(self):
        """Initialize the PJSIP library. Called once by the worker thread."""
        logger.info("Initializing native library")
        self.__ep = pj.Endpoint()
        # N.B.: from PJSIP's perspective, the thread that calls
        # libCreate() is the main thread. Combined with
        # ``uaConfig.mainThreadOnly``, this ensures that all PJSIP
        # events will be handled here, and not by any native threads.
        self.__ep.libCreate()
        self.__ep.libInit(Config.endpoint_config())
        self.__ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, Config.transport_config())
        Config.setup_audio(self.__ep)
        self.__ep.libStart()

        logger.debug("Creating account")
        self.__account = AccountCallback()
        self.__account.create(Config.account_config())

        self.__phone.dialtone = DialTonePlayer(**Config.dialtone_config())
        self.__phone.recorder = CallRecorder(**Config.recorder_config())

        # Make sure the library can fully start up
        while True:
            e = self.__ep.libHandleEvents(20)  # note: libHandleEvents() takes milliseconds
            if e == 0: break
            if e < 0:
                raise RuntimeError("Error while initializing PJSUA2: {msg} ({errno})"
                                   .format(errno=-e, msg=self.__ep.utilStrError(-e)))
        logger.debug("Initialization complete")

    def handleNativeEvents(self):
        e = self.__ep.libHandleEvents(0)
        if e < 0:
            raise RuntimeError("Error while handling PJSUA2 native events: {msg} ({errno})"
                               .format(errno=-e, msg=self.__ep.utilStrError(-e)))

    def checkHangupAll(self):
        """Check if hanging up all calls was requested"""

        if self.hangup < 1: return

        with self.__phone._Pjsua2__call_lock:
            prm = pj.CallOpParam()
            self.__waiting_calls = []

            for c in self.__ringing_calls:
                c.hangup(prm)
            self.__ringing_calls = []

            if self.current_call is not None:
                self.current_call.hangup(prm)
            else:
                # Synthesize a disconnect event
                fire_event("OnCallDisconnect", remote_uri="sip:null@null")
            self.ready.release(self.hangup)
            self.hangup = 0

    def checkCallTime(self):
        """Check all current calls and enforce call time restrictions"""

        if self.__phone.current_call is None and len(self.__phone._Pjsua2__ringing_calls) == 0:
            return

        eh = DoorPi().event_handler
        with self.__phone._Pjsua2__call_lock:
            c = self.__phone.current_call
            if c is not None:
                ci = c.getInfo()
                if self.__max_call_time > 0 \
                    and ci.state == pj.PJSIP_INV_STATE_CONFIRMED \
                    and ci.connectDuration.sec >= self.__max_call_time:
                    logger.info("Hanging up call to %s after %d seconds",
                                repr(ci.remoteUri), self.__max_call_time)
                    prm = pj.CallOpParam()
                    c.hangup(prm)
                    self.__phone.current_call = None
            else:
                synthetic_disconnect = False
                prm = pj.CallOpParam()
                for c in self.__phone._Pjsua2__ringing_calls:
                    ci = c.getInfo()
                    if ci.totalDuration.sec >= self.__call_timeout:
                        logger.info("Call to %s unanswered after %d seconds, giving up",
                                    repr(ci.remoteUri), self.__call_timeout)
                        c.hangup(prm)
                        self.__phone._Pjsua2__ringing_calls.remove(c)
                        synthetic_disconnect = True
                if synthetic_disconnect and len(self.__phone._Pjsua2__ringing_calls) == 0:
                    # All calls went unanswered. Synthesize a disconnect event.
                    fire_event("OnCallDisconnect", remote_uri="sip:null@null")

    def createCalls(self):
        """Create requested outbound calls"""
        if len(self.__phone._Pjsua2__waiting_calls) == 0:
            return

        with self.__phone._Pjsua2__call_lock:
            for uri in self.__phone._Pjsua2__waiting_calls:
                logger.info("Calling %s", uri)
                fire_event("OnCallOutgoing", remote_uri=uri)
                call = CallCallback(self.__account)
                callprm = pj.CallOpParam(True)
                try: call.makeCall(uri, callprm)
                except pj.Error as err:
                    logger.error("Error making a call: %s", err.info())
                    raise
                self.__phone._Pjsua2__ringing_calls += [call]
            self.__phone._Pjsua2__waiting_calls = []
