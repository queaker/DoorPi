# -*- coding: utf-8 -*-

import logging
logger = logging.getLogger(__name__)
logger.debug("%s loaded", __name__)

import os
from mimetypes import guess_type
from http.server import BaseHTTPRequestHandler
import cgi # for parsing POST
from urllib.parse import urlparse, parse_qs # parsing parameters and url
import re # regex for area
import json # for virtual resources
from urllib.parse import unquote_plus

from doorpi.action.base import SingleAction
import doorpi
from .request_handler_static_functions import *

VIRTUELL_RESOURCES = [
    '/mirror',
    '/status',
    '/control/trigger_event',
    '/control/config_value_get',
    '/control/config_value_set',
    '/control/config_value_delete',
    '/control/config_save',
    '/control/config_get_configfile',
    '/help/modules.overview.html'
]

PARSABLE_FILE_EXTENSIONS = ["html"]

DOORPIWEB_SECTION = 'DoorPiWeb'

class WebServerLoginRequired(Exception): pass
class WebServerRequestHandlerShutdownAction(SingleAction): pass

class DoorPiWebRequestHandler(BaseHTTPRequestHandler):

    @property
    def conf(self): return self.server.config

    def log_error(self, format, *args): logger.error("[%s] %s", self.client_address[0], args)
    def log_message(self, format, *args): logger.debug("[%s] %s", self.client_address[0], args)

    @staticmethod
    def prepare():
        doorpi.DoorPi().event_handler.register_event('OnWebServerRequest', __name__)
        doorpi.DoorPi().event_handler.register_event('OnWebServerRequestGet', __name__)
        doorpi.DoorPi().event_handler.register_event('OnWebServerRequestPost', __name__)
        doorpi.DoorPi().event_handler.register_event('OnWebServerVirtualResource', __name__)
        doorpi.DoorPi().event_handler.register_event('OnWebServerRealResource', __name__)

        # for do_control
        doorpi.DoorPi().event_handler.register_event('OnFireEvent', __name__)
        doorpi.DoorPi().event_handler.register_event('OnConfigKeySet', __name__)
        doorpi.DoorPi().event_handler.register_event('OnConfigKeyDelete', __name__)

    @staticmethod
    def destroy():
        doorpi.DoorPi().event_handler.unregister_source( __name__, True)

    def do_GET(self):
        #doorpi.DoorPi().event_handler('OnWebServerRequest', __name__)
        if not self.server.keep_running: return

        parsed_path = urlparse(self.path)
        #doorpi.DoorPi().event_handler('OnWebServerRequest', __name__, {'header': self.headers.items(), 'path': parsed_path})
        #doorpi.DoorPi().event_handler('OnWebServerRequestGet', __name__, {'header': self.headers.items(), 'path': parsed_path})

        if parsed_path.path == "/":
            return self.return_redirection('dashboard/pages/index.html')

        if self.authentication_required(): return self.login_form()

        #doorpi.DoorPi().event_handler('OnWebServerRequestGet', __name__)

        if parsed_path.path in VIRTUELL_RESOURCES:
            return self.create_virtual_resource(parsed_path, parse_qs(urlparse(self.path).query))
        else: return self.real_resource(parsed_path.path)

    def do_control(self, control_order, para):
        result_object = dict(
            success = False,
            message = 'unknown error'
        )
        logger.debug(json.dumps(para, sort_keys = True, indent = 4))

        for parameter_name in list(para.keys()):
            try: para[parameter_name] = unquote_plus(para[parameter_name][0])
            except LookupError: para[parameter_name] = ''

        if control_order == "trigger_event":
            result_object['message'] = doorpi.DoorPi().event_handler.fire_event_synchron(**para)
            if result_object['message'] is True:
                result_object['success'] = True
                result_object['message'] = "fire Event was success"
            else:
                result_object['success'] = False
        elif control_order == "config_value_get":
            # section, key, default, store
            result_object['success'] = True
            result_object['message'] = control_config_get_value(**para)
        elif control_order == "config_value_set":
            # section, key, value, password
            result_object['success'] = control_config_set_value(**para)
            result_object['message'] = "config_value_set %s" % (
                'success' if result_object['success'] else 'failed'
            )
        elif control_order == "config_value_delete":
            # section and key
            result_object['success'] = control_config_delete_key(**para)
            result_object['message'] = "config_value_delete %s" % (
                'success' if result_object['success'] else 'failed'
            )
        elif control_order == "config_save":
            # configfile
            result_object['success'] = control_config_save(**para)
            result_object['message'] = "config_save %s" % (
                'success' if result_object['success'] else 'failed'
            )
        elif control_order == "config_get_configfile":
            result_object['message'] = control_config_get_configfile()
            result_object['success'] = True if result_object['message'] != "" else False

        return result_object

    def clear_parameters(self, raw_parameters):
        if 'module' not in list(raw_parameters.keys()): raw_parameters['module'] = []
        if 'name' not in list(raw_parameters.keys()): raw_parameters['name'] = []
        if 'value' not in list(raw_parameters.keys()): raw_parameters['value'] = []
        return raw_parameters

    def create_virtual_resource(self, path, raw_parameters):
        return_object = {}
        if path.path == '/mirror':
            return_object = self.create_mirror()
            raw_parameters['output'] = "string"
        elif path.path == '/status':
            raw_parameters = self.clear_parameters(raw_parameters)
            return_object = doorpi.DoorPi().get_status(
                modules = raw_parameters['module'],
                name = raw_parameters['name'],
                value = raw_parameters['value']
            ).dictionary
        elif path.path.startswith('/control/'):
            return_object = self.do_control(path.path.split('/')[-1], raw_parameters)
        elif path.path == '/help/modules.overview.html':
            raw_parameters = self.clear_parameters(raw_parameters)
            return_object, mime = self.get_file_content('/dashboard/parts/modules.overview.html')
            return_object = self.parse_content(
                return_object,
                MODULE_AREA_NAME = raw_parameters['module'][0] or '',
                MODULE_NAME = raw_parameters['name'][0] or ''
            )
            raw_parameters['output'] = "html"

        if 'output' not in list(raw_parameters.keys()): raw_parameters['output'] = ''
        return self.return_virtual_resource(return_object, raw_parameters['output'])

    def return_virtual_resource(self, prepared_object, return_type = 'json'):
        if isinstance(return_type, list) and len(return_type) > 0: return_type = return_type[0]

        if return_type in ["json", "default"]:
            return  self.return_message(json.dumps(prepared_object), "application/json; charset=utf-8")
        if return_type in ["json_parsed", "json.parsed"]:
            return  self.return_message(self.parse_content(json.dumps(prepared_object)), "application/json; charset=utf-8")
        elif return_type in ["json_beautified", "json.beautified", "beautified.json"]:
            return  self.return_message(json.dumps(prepared_object, sort_keys=True, indent=4), "application/json; charset=utf-8")
        elif return_type in ["json_beautified_parsed", "json.beautified.parsed", "beautified.json.parsed", ""]:
            return  self.return_message(self.parse_content(json.dumps(prepared_object, sort_keys=True, indent=4)), "application/json; charset=utf-8")
        elif return_type in ["string", "plain", "str"]:
            return self.return_message(str(prepared_object))
        elif return_type in ["repr"]:
            return self.return_message(repr(prepared_object))
        elif return_type is 'html':
            return self.return_message(prepared_object, 'text/html; charset=utf-8')
        else:
            try:    return self.return_message(repr(prepared_object))
            except: return self.return_message(str(prepared_object))

    def real_resource(self, path):
        #doorpi.DoorPi().event_handler('OnWebServerRealResource', __name__, {'path': path})
        if os.path.isdir(self.server.www + path): return self.list_directory(self.server.www + path)
        return self.return_file_content(path)

    def list_directory(self, path):
        dirs = []
        files = []
        for item in os.listdir(path):
            if os.path.isfile(item): files.append(item)
            else: dirs.append(item)

        return_html = '''<!DOCTYPE html>
            <html lang="en"><head></head><body><a href="..">..</a></br>
        '''
        for dir in dirs: return_html += '<a href="./{dir}">{dir}</a></br>'.format(dir = dir)
        for file in files: return_html += '<a href="./{file}">{file}</a></br>'.format(file = file)
        return_html += "</body></html>"
        return self.return_message(return_html, 'text/html')
        #return self.send_error(403)

    def return_redirection(self, new_location):
        message = '''
        <html>
        <meta http-equiv="refresh" content="0;url={new_location}">
        <a href="{new_location}">{new_location}</a>
        </html>
        '''.format(new_location = new_location)
        return self.return_message(message, 'text/html', http_code = 301)

    @staticmethod
    def get_mime_typ(url):
        return guess_type(url)[0] or ""

    @staticmethod
    def is_file_parsable(filename):
        ext = filename.split(".")[-1]
        return ext in PARSABLE_FILE_EXTENSIONS

    def read_from_file(self, url, template_recursion = 5):
        # protect against directory traversal
        url = os.path.realpath(url)
        if not url.startswith(self.server.www): raise FileNotFoundError

        read_mode = "r" if self.is_file_parsable(url) else "rb"
        with open(url, read_mode) as file:
            file_content = file.read()
        if self.is_file_parsable(url):
            return self.parse_content(file_content, template_recursion=template_recursion)
        else:
            return file_content

    def get_file_content(self, path):
        content = mime = ""
        content = self.read_from_file(self.server.www + path)
        mime = self.get_mime_typ(self.server.www + path)

        return content, mime

    def return_file_content(self, path):
        content, mime = self.get_file_content(path)
        return self.return_message(
            content, mime
        )

    def return_message(self, message = "", content_type = 'text/plain; charset=utf-8', http_code = 200,):
        self.send_response(http_code)
        self.send_header('WWW-Authenticate', 'Basic realm=\"%s\"' % doorpi.DoorPi().name_and_version)
        self.send_header("Server", doorpi.DoorPi().name_and_version)
        self.send_header("Content-type", content_type)
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(message.encode("utf-8") if type(message) is str else message)

    def login_form(self):
        return self.return_message(http_code = 401)

    def authentication_required(self):
        try:
            parsed_path = urlparse(self.path)

            public_resources = self.conf.get_keys(self.server.area_public_name, log = False)
            for public_resource in public_resources:
                if re.match(public_resource, parsed_path.path):
                    logger.debug('public resource: %s',parsed_path.path)
                    return False

            username, password = self.headers['authorization'].replace('Basic ', '').decode('base64').split(':', 1)

            user_session = self.server.sessions.get_session(username)
            if not user_session:
                user_session = self.server.sessions.build_security_object(username, password)

            if not user_session:
                logger.debug('need authentication (no session): %s', parsed_path.path)
                return True

            for write_permission in user_session['writepermissions']:
                if re.match(write_permission, parsed_path.path):
                    logger.info('user %s has write permissions: %s', user_session['username'], parsed_path.path)
                    return False

            for read_permission in user_session['readpermissions']:
                if re.match(read_permission, parsed_path.path):
                    logger.info('user %s has read permissions: %s', user_session['username'], parsed_path.path)
                    return False

            logger.warning('user %s has no permissions: %s', user_session['username'], parsed_path.path)
            return True
        except: return True

    def check_authentication(self):
        if not self.authentication_required(): return True
        raise WebServerLoginRequired()

    def create_mirror(self):
        parsed_path = urlparse(self.path)
        message_parts = [
                'CLIENT VALUES:',
                'client_address=%s (%s)' % (self.client_address,
                                            self.address_string()),
                'raw_requestline=%s' % self.raw_requestline,
                'command=%s' % self.command,
                'path=%s' % self.path,
                'real path=%s' % parsed_path.path,
                'query=%s' % parsed_path.query,
                'request_version=%s' % self.request_version,
                '',
                'SERVER VALUES:',
                'server_version=%s' % self.server_version,
                'sys_version=%s' % self.sys_version,
                'protocol_version=%s' % self.protocol_version,
                '',
                'HEADERS RECEIVED:',
        ]
        for name, value in sorted(self.headers.items()):
            message_parts.append('%s=%s' % (name, value.rstrip()))
        message_parts.append('')
        message = '\r\n'.join(message_parts)
        return message

    def parse_content(self, content, template_recursion = 5, **mapping_table):
        if type(content) != str:
            raise TypeError("content must be of type str")

        mapping_table['DOORPI'] =           doorpi.DoorPi().name_and_version
        mapping_table['SERVER'] =           self.server.server_name
        mapping_table['PORT'] =             str(self.server.server_port)
        mapping_table['MIN_EXTENSION'] =    '' if logger.getEffectiveLevel() <= 5 else '.min'

        # Templates:
        mapping_table['TEMPLATE:HTML_HEADER'] =     'html.header.html'
        mapping_table['TEMPLATE:HTML_FOOTER'] =     'html.footer.html'
        mapping_table['TEMPLATE:NAVIGATION'] =      'navigation.html'

        for k in list(mapping_table.keys()):
            # template_recursion: don't process {TEMPLATE:...} if we're inside one
            if template_recursion and k.startswith('TEMPLATE:'):
                # exceptions are deliberately ignored and will result in HTTP error 500
                content = content.replace('{'+k+'}', self.read_from_file(os.path.join(self.server.www, 'dashboard', 'parts', mapping_table[k]), template_recursion=template_recursion-1))
            else:
                content = content.replace('{'+k+'}', mapping_table[k])
        return content
