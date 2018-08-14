#!/usr/bin/env python

import os
import sys
import re
import yaml

try:
    import ruamel.yaml as rtyaml
except ImportError:
    rtyaml = None


def get_yaml_conf_dir():
    current_script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    if "/collectors/0" in current_script_dir:
        yaml_conf_dir = os.path.join(current_script_dir[:current_script_dir.index("/collectors/0")], 'conf')
    else:
        yaml_conf_dir = os.path.join(current_script_dir, 'conf')
    return yaml_conf_dir


def load_collector_configuration(config_file):
    yaml_conf_dir = get_yaml_conf_dir()
    return load_configuration(yaml_conf_dir, config_file)


def load_configuration(yaml_conf_dir, config_file):
    with open(os.path.join(yaml_conf_dir, config_file), 'r') as stream:
        try:
            return yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            print("Type error: {0}".format(exc))


def to_dict(global_tags_string):
    global_tags_string = re.sub(r'\s+', '', global_tags_string)
    global_tags_string = global_tags_string.replace(';', ',')
    global_tags_string = global_tags_string.replace(':', '=')
    return dict(x.split('=') for x in global_tags_string.split(','))


def set_global_tags(global_tags_string, overwrite=False, conf_path=None):
    if conf_path is None:
        conf_path = os.path.join(get_yaml_conf_dir(), "xcollector.yml")

    with open(conf_path, 'r') as stream:
        if rtyaml:
            root = rtyaml.round_trip_load(stream)
        else:
            root = yaml.safe_load(stream)

        if root['collector'] is None or 'config' not in root['collector']:
            raise ConfigurationException(
                "Can not find collector/config in the config file [%s]" % conf_path)
        if "tags" in root['collector']['config'] and (not overwrite):
            return False

        try:
            root['collector']['config']['tags'] = to_dict(global_tags_string)
        except ValueError as error:
            raise ConfigurationException(
                "Invalid tag format [%s]. Expected format -> key1=value1, key2=value2."
                % global_tags_string, error)

    with open(conf_path, "w") as stream:
        if rtyaml:
            rtyaml.round_trip_dump(root, stream, default_flow_style=False)
        else:
            yaml.dump(root, stream, default_flow_style=False)

    return True


class ConfigurationException(Exception):
    pass
