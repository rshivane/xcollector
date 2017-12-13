#!/usr/bin/env python

import os
import sys
from collectors.lib import poyo


def load_collector_configuration(config_file):
    current_script_dir = os.path.dirname(os.path.realpath(sys.argv[0]))
    if "/collectors/0" in current_script_dir:
        yaml_conf_dir = os.path.join(current_script_dir[:current_script_dir.index("/collectors/0")], 'conf')
    else:
        yaml_conf_dir = os.path.join(current_script_dir, 'conf')
    with open(os.path.join(yaml_conf_dir, config_file), 'r') as stream:
        try:
            return poyo.parse_string(stream.read())
        except poyo.PoyoException as exc:
            print("Type error: {0}".format(exc))
