# -*- coding: utf-8 -*-

import logging
logger = logging.getLogger(__name__)
logger.debug("%s loaded", __name__)

try: import docutils.core
except ModuleNotFoundError:
    logger.error("docutils are not installed; dependency status in web interface will be incomplete")
import importlib
import json

DEFAULT_MODULE_ATTR = ['__doc__', '__file__', '__name__', '__package__', '__path__', '__version__']

def check_module_status(module):
    module['is_fulfilled'] = False if module['fulfilled_with_one'] else True
    for module_name in list(module['libraries'].keys()):
        status = {}
        try:
            package = importlib.import_module(module_name)
            content = dir(package)

            for attr in DEFAULT_MODULE_ATTR:
                if attr in content:
                    status[attr.replace('__', '')] = getattr(package, attr) or ''
                else:
                    status[attr.replace('__', '')] = 'unknown'

            status['installed'] = True
            if module['fulfilled_with_one']: module['is_fulfilled'] = True
            status['content'] = content

        except Exception as exp:
            status = {'installed': False, 'error': str(exp)}
            if not module['fulfilled_with_one']: module['is_fulfilled'] = False

        finally:
            module['libraries'][module_name]['status'] = status

    return module

def rsttohtml(rst):
    try:
        return docutils.core.publish_parts(rst, writer_name='html', settings_overrides={'input_encoding': 'unicode'})['fragment']
    except NameError: # docutils not installed
        return "(cannot render text: docutils not installed)"

def load_module_status(module_name):
    module = importlib.import_module('doorpi.status.requirements_lib.'+module_name).REQUIREMENT

    # parse reStructuredText descriptions to HTML:
    # the top-level module.text_description
    try: module['text_description'] = rsttohtml(module['text_description'])
    except KeyError: pass
    # module.libraries.*.[text_description, text_warning, text_test]
    for lib in module['libraries'].keys():
        for ent in ['text_description', 'text_warning', 'text_test']:
            try: module['libraries'][lib][ent] = rsttohtml(module['libraries'][lib][ent])
            except KeyError: pass
    # module.[configuration, events].*.description
    for ent in ['configuration', 'events']:
        try:
            for sub in range(len(module[ent])):
                try:
                    module[ent][sub]['description'] = rsttohtml(module[ent][sub]['description'])
                    logger.trace('Parsed {}.{}.{}.description'.format(module_name, ent, sub))
                except KeyError: pass
        except KeyError: pass

    return check_module_status(module)

REQUIREMENTS_DOORPI = {
    'config':           load_module_status('req_config'),
    'sipphone':         load_module_status('req_sipphone'),
    'event_handler':    load_module_status('req_event_handler'),
    'webserver':        load_module_status('req_webserver'),
    'keyboard':         load_module_status('req_keyboard'),
    'system':           load_module_status('req_system')
}

def get(*args, **kwargs):
    try:
        if len(kwargs['name']) == 0: kwargs['name'] = ['']
        if len(kwargs['value']) == 0: kwargs['value'] = ['']

        status = {}
        for name_requested in kwargs['name']:
            for possible_name in list(REQUIREMENTS_DOORPI.keys()):
                if name_requested in possible_name:
                    status[possible_name] = REQUIREMENTS_DOORPI[possible_name]

        return status
    except Exception as exp:
        logger.exception(exp)
        return {'Error': 'could not create '+str(__name__)+' object - '+str(exp)}

def is_active(doorpi_object):
    return True
