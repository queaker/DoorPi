# -*- coding: utf-8 -*-

import os
import logging
logger = logging.getLogger(__name__)
logger.debug("%s loaded", __name__)

from http.server import HTTPServer
from socketserver import ThreadingMixIn
import socket

from random import randrange

import doorpi
from doorpi.action.base import SingleAction

from doorpi.status.webserver_lib.session_handler import SessionHandler
from doorpi.status.webserver_lib.request_handler import DoorPiWebRequestHandler

class WebServerStartupAction(SingleAction): pass
class WebServerFakeRequestAction(SingleAction): pass
class WebServerShutdownAction(SingleAction): pass
class WebServerInformUrl(SingleAction): pass

DOORPIWEB_SECTION = 'DoorPiWeb'
CONF_AREA_PREFIX = 'AREA_'

def load_webserver():
    ip = doorpi.DoorPi().config.get(DOORPIWEB_SECTION, 'ip', '0.0.0.0')
    port = doorpi.DoorPi().config.get_int(DOORPIWEB_SECTION, 'port', 50371)

    doorpiweb_object = None

    logger.info("Starting WebService")
    try:
        server_address = (ip, port)
        doorpiweb_object = DoorPiWeb(server_address, DoorPiWebRequestHandler)
        doorpiweb_object.start()
    except Exception as exp:
        logger.error("Starting WebService failed: {msg}".format(msg=exp))
        logger.exception(exp)

    return doorpiweb_object

def check_config(config):
    errors = []
    warnings = []
    infos = []

    groups_with_write_permissions = config.get_keys('WritePermission')
    groups_with_read_permissions = config.get_keys('ReadPermission')
    groups = config.get_keys('Group')
    users = config.get_keys('User')

    if len(groups) == 0:
        errors.append('no groups in configfile!')

    if len(groups_with_write_permissions) == 0:
        errors.append("no WritePermission found")

    for group in groups_with_write_permissions:
        if group not in groups: warnings.append("group %s doesn't exist but is assigned to WritePermission" % group)

    if len(groups_with_read_permissions) == 0:
        warnings.append("no ReadPermission found")

    for group in groups_with_read_permissions:
        if group not in groups: warnings.append("group %s doesn't exist but is assigned to ReadPermission" % group)

    for group in groups:
        users_in_group = config.get_list('Group', group)
        for user_in_group in users_in_group:
            if user_in_group not in users:
                warnings.append("user %s is assigned to group %s but doesn't exist as user" % (user_in_group, group))

    config_section = config.get_sections()

    for group in groups_with_write_permissions:
        modules = config.get_list('WritePermission', group)
        for module in modules:
            if CONF_AREA_PREFIX+module not in config_section:
                warnings.append("module %s doesn't exist but is assigned to group %s in WritePermission" % (module, group))

    for group in groups_with_read_permissions:
        modules = config.get_list('ReadPermission', group)
        for module in modules:
            if CONF_AREA_PREFIX+module not in config_section:
                warnings.append("module %s doesn't exist but is assigned to group %s in ReadPermission" % (module, group))

    for info in infos: logger.info(info)
    for warning in warnings: logger.error(warning)
    for error in errors: logger.error(error)

    return {'infos': infos, 'warnings': warnings, 'errors': errors}

class DoorPiWeb(ThreadingMixIn, HTTPServer):
    keep_running = True

    www = None
    indexfile = None
    base_url = None
    area_public_name = None

    @property
    def config_status(self): return check_config(self.config)

    @property
    def own_url(self):
        if self.server_port is 80:
            return "http://%s/"%self.server_name
        else:
            return "http://%s:%s/"%(self.server_name, self.server_port)

    def inform_own_url(self): logger.info('DoorPiWeb URL is %s', self.own_url)

    @property
    def sessions(self):
        if not self._session_handler and self.keep_running:
            logger.debug('no session handler - creating it now')
            self._session_handler = SessionHandler()
        return self._session_handler
    _session_handler = None

    @property
    def config(self): return doorpi.DoorPi().config

    def start(self):
        logger.info("Starting WebServer on {}".format(self.own_url))
        doorpi.DoorPi().event_handler.register_event('OnWebServerStart', __name__)
        doorpi.DoorPi().event_handler.register_event('OnWebServerStop', __name__)

        self.www = os.path.realpath(doorpi.DoorPi().config.get_string_parsed(DOORPIWEB_SECTION, 'www', '!BASEPATH!/../DoorPiWeb'))
        self.indexfile = doorpi.DoorPi().config.get_string_parsed(DOORPIWEB_SECTION, 'indexfile', 'index.html')
        self.area_public_name = doorpi.DoorPi().config.get_string_parsed(DOORPIWEB_SECTION, 'public', 'AREA_public')
        check_config(self.config)
        logger.info("Serving files from {}".format(self.www))

        doorpi.DoorPi().event_handler.register_action('OnWebServerStart', WebServerStartupAction(self.serve_forever))
        doorpi.DoorPi().event_handler.register_action('OnShutdown', WebServerShutdownAction(self.init_shutdown))
        doorpi.DoorPi().event_handler('OnWebServerStart', __name__)

        DoorPiWebRequestHandler.prepare()
        logger.info("WebServer started")
        return self

    def fake_request(self):
        try:
            from urllib.request import urlopen as fake_request
            fake_request("http://%s:%s/"%(self.server_name, self.server_port), timeout = 0)
        except: pass

    def init_shutdown(self):
        doorpi.DoorPi().event_handler('OnWebServerStop', __name__)
        self.shutdown()
        if self.sessions: self.sessions.destroy()
        DoorPiWebRequestHandler.destroy()
        self.fake_request()
        doorpi.DoorPi().event_handler.unregister_source(__name__, True)

    def server_bind(self):
        listen_fds = int(os.environ.get("LISTEN_FDS", 0))
        if listen_fds > 0:
            logger.trace("Passed in fds: {}".format(listen_fds))
            fd = 3 # FIXME don't use a magic number; this is SD_LISTEN_FDS_START in <systemd/sd-daemon.h>
            self.socket = socket.fromfd(fd, socket.AF_INET, socket.SOCK_STREAM)
            # fake out some info that isn't readily available in this mode
            self.server_name = "<your-raspberry-ip>:port"
            self.server_port = 80
        else:
            super().server_bind()

    def server_activate(self):
        listen_fds = int(os.environ.get("LISTEN_FDS", 0))
        if listen_fds > 0:
            pass
        else:
            super().server_activate()
