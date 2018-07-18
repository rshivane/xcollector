#!/usr/bin/env python
import logging
import os
import tempfile
import fnmatch
import copy
import re
import requests
import signal
import subprocess
import sys
import calendar
import time
import yaml
import traceback

from io import StringIO

from collectors.etc import grok_scraper_conf
from collectors.lib import utils

COLLECTION_INTERVAL_SECONDS = 15
MATCHING_FILE_POLLING_INTERVAL_SECONDS = 1

grok_scraper_basename = None
yconfig = {}
file_being_groked = None
processes = []
urls_vs_patterns = {}

logging.basicConfig(stream=sys.stderr)
LOG = logging.getLogger('grok_scraper')
LOG.setLevel(logging.INFO)


def launch_grokker(exporter_dir, config, generate_debug_log):
    try:
        debug_log_fd = open(os.devnull, 'w')
        if generate_debug_log:
            debug_log_fd = sys.stderr
        # No need to set the setsid or do pgkill here since we know grokker does not launch any subprocesses
        proc = subprocess.Popen([exporter_dir + '/grok_exporter', '-config',
                                 config],
                                stdout=debug_log_fd,
                                stderr=subprocess.STDOUT,
                                close_fds=True,
                                cwd=exporter_dir)
        processes.append(proc)
    except Exception as e:
        traceback.print_exc()
        die()


def load_metric_patterns(ycfg):
    metrics = ycfg['metrics']
    patterns = []
    for metric in metrics:
        metric_name = metric['name']
        if metric['type'] in ('histogram', 'summary'):
            pattern = re.compile(
                '^(%s)([^\}]*[\}]*)(\s+[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)' % (metric_name + '_count'))
            patterns.append(pattern)
            pattern = re.compile(
                '^(%s)([^\}]*[\}]*)(\s+[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)' % (metric_name + '_sum'))
            patterns.append(pattern)
        pattern = re.compile('^(%s)([^\}]*[\}]*)(\s+[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)' % metric_name)
        patterns.append(pattern)
    host = ycfg['server']['host']
    port = ycfg['server']['port']
    urls_vs_patterns['http://%s:%d/metrics' % (host, port)] = patterns


def have_dead_grokkers():
    '''
    Poll returns the exitcode after a while (not immediately), since it's not populated until after the subprocess has failed.
    '''
    for p in processes:
        poll = p.poll()
        if poll is not None:  # has exited
            return True
    return False


def kill_grokkers():
    for proc in processes:
        exit_code = proc.poll()
        if exit_code is None:
            proc.terminate()
        else:
            LOG.error("Grokker with pid [%d] exited with code: [%d]", proc.pid, exit_code)
    for proc in processes:
        proc.wait()
        processes.remove(proc)


def gcd(a, b):
    while b > 0:
        a, b = b, a % b
    return a


def start_poller(exporter_dir, config_file_path, grok_exporter_debug):
    global file_being_groked

    pattern_based_path = (yconfig['input']['type'] == "file-name-pattern")

    sleep_duration = gcd(COLLECTION_INTERVAL_SECONDS, MATCHING_FILE_POLLING_INTERVAL_SECONDS)

    cur_time = calendar.timegm(time.gmtime())
    last_fetch_time = cur_time
    last_file_poll_time = cur_time

    launch_grokker(exporter_dir, config_file_path, grok_exporter_debug)
    time.sleep(COLLECTION_INTERVAL_SECONDS)  # Give enough time for the grokker to launch

    while True:
        cur_time = calendar.timegm(time.gmtime())

        if cur_time >= (last_fetch_time + COLLECTION_INTERVAL_SECONDS):
            if have_dead_grokkers():
                die()
            fetch_metrics()
            last_fetch_time = cur_time

        if pattern_based_path and cur_time >= (last_file_poll_time + MATCHING_FILE_POLLING_INTERVAL_SECONDS):
            last_file_poll_time = cur_time
            latest_file = check_latest_file()
            if file_being_groked == latest_file:
                continue

            if cur_time >= last_fetch_time:
                fetch_metrics()
                last_fetch_time = cur_time
            kill_grokkers()
            os.remove(config_file_path)

            config_file_path = create_grok_config(yconfig, latest_file)
            launch_grokker(exporter_dir, config_file_path, grok_exporter_debug)
            file_being_groked = latest_file
        time.sleep(sleep_duration)


def check_latest_file():
    input_path = yconfig['input']['path']
    input_file_pattern = yconfig['input']['pattern']
    latest_file = find_latest_file(input_path, input_file_pattern)
    if latest_file is None:
        LOG.error("Could not find any file that matches the pattern [" + input_file_pattern +
                  "] in the folder [" + input_path + "]")
        die()
    latest_file = os.path.join(input_path, latest_file)
    if not os.access(input_path, os.R_OK):
        LOG.error("The file " + input_path +
                  " does not exist or xcollector does not have read permissions to it")
        die()
    return latest_file


def load_config(config_file_path):
    global yconfig, file_being_groked

    if not os.access(config_file_path, os.R_OK):
        LOG.error("The file " + config_file_path + " does not exist or xcollector does not have read permissions to it")
        die()

    with open(config_file_path, 'r') as stream:
        try:
            yconfig = yaml.load(stream)
        except yaml.YAMLError as exc:
            LOG.error("Error parsing grokker config: {0}".format(exc))
            die()
        if 'input' not in yconfig or 'path' not in yconfig['input']:
            LOG.error("Improper grokker config as argument")
            die()
        input_path = yconfig['input']['path']
        input_type = yconfig['input']['type']

        if input_type == "file-name-pattern":
            if not os.path.exists(input_path):
                LOG.error("The folder " + input_path + " does not exist")
                die()
            if not os.access(input_path, os.R_OK):
                LOG.error("Can't read the folder: " + input_path)
                die()
            if 'pattern' not in yconfig['input']:
                LOG.error("Can't find input filename pattern in the config")
                die()
            input_file_pattern = yconfig['input']['pattern']
            latest_file = find_latest_file(input_path, input_file_pattern)
            if latest_file is None:
                LOG.error("Could not find any file that matches the pattern [" + input_file_pattern +
                          "] in the folder [" + input_path + "]")
                die()
            else:
                input_path = os.path.join(input_path, latest_file)
                config_file_path = create_grok_config(yconfig, input_path)

        if not os.access(input_path, os.R_OK):
            LOG.error("The file " + input_path + " does not exist or xcollector does not have read permissions to it")
            die()
        file_being_groked = input_path
        load_metric_patterns(yconfig)
    return config_file_path


def create_grok_config(orig_config, input_path):
    yconfig = copy.deepcopy(orig_config)
    yconfig['input']['type'] = "file"
    yconfig['input']['path'] = input_path
    del yconfig['input']['pattern']
    new_config = tempfile.NamedTemporaryFile(prefix=grok_scraper_basename + "-", suffix=".conf").name
    with open(new_config, "w") as output_stream:
        yaml.dump(yconfig, output_stream, default_flow_style=False)
    return new_config


def find_latest_file(path, file_name_pattern):
    latest_file = None
    latest_file_time = -1
    folder_listing = os.listdir(path)
    folder_listing = fnmatch.filter(folder_listing, file_name_pattern)
    for f in folder_listing:
        f_path = os.path.join(path, f)
        if os.path.isfile(f_path):
            stat = os.stat(f_path)
            f_time = stat.st_mtime
            try:
                f_time = stat.st_birthtime
            except AttributeError:
                pass  # Python on Linux does not support getting creation time
            if f_time > latest_file_time:
                latest_file = f
                latest_file_time = f_time
    return latest_file


def munge_metric_name(metric):
    new_name = re.sub(r'__', '\0', metric)
    found_double_underscore = (len(new_name) < len(metric))
    new_name = re.sub(r'_', ".", new_name)
    if found_double_underscore:
        new_name = re.sub(r'\0', "_", new_name)
    return new_name


def main():
    signal.signal(signal.SIGTERM, die)
    exporter_dir = grok_scraper_conf.get_grok_exporter_dir()
    scraper_dir = grok_scraper_conf.get_grok_scraper_config_dir()
    grok_exporter_debug = grok_scraper_conf.get_grok_exporter_debug()

    global grok_scraper_basename
    grok_scraper_basename = os.path.basename(__file__)
    grok_scraper_basename = grok_scraper_basename[0:grok_scraper_basename.index('.')]
    config_file_name = grok_scraper_basename + ".yml"
    config_file_path = os.path.join(scraper_dir, config_file_name)
    config_file_path = load_config(config_file_path)
    start_poller(exporter_dir, config_file_path, grok_exporter_debug)


def die(signum=signal.SIGTERM, stack_frame=None):
    kill_grokkers()
    exit(13)  # Signal to tcollector


def fetch_metrics():
    def format_metric_value(value):
        float_value = float(value)
        if float_value.is_integer():
            return int(float_value)
        else:
            return "{0:.3f}".format(float_value)

    def print_metric(metric_name, timestamp, value, tags):
        print("%s %s %s %s" % (munge_metric_name(metric_name), timestamp, format_metric_value(value), tags))

    for (url, patterns) in urls_vs_patterns.items():
        try:
            response = requests.get(url)
            timestamp = int(time.time())
            global buf
            buf = StringIO(response.text)
            for line in buf.readlines():
                for pattern in patterns:
                    matcher = pattern.search(line)
                    if matcher is None:
                        continue
                    g = matcher.groups()
                    if g[1].startswith('_count'):
                        continue
                    elif g[1].startswith('_sum'):
                        continue
                    tags = ' '.join(g[1].replace('"', '').strip('{}').split(','))
                    if '::_' in g[0]:
                        extratags = g[0].split('::_')
                        global finalmetricname
                        finalmetricname = extratags[0]
                        for i, extratag in enumerate(extratags):
                            if i == 0:
                                continue
                            elif extratag.startswith('_'):
                                finalmetricname += extratag
                            else:
                                tags += ' ' + extratag.replace('_', '=')
                        print_metric(finalmetricname, timestamp, g[2], tags)
                    else:
                        print_metric(g[0], timestamp, g[2], tags)
        except:
            utils.err("Unexpected error: %s" % sys.exc_info()[0])
            traceback.print_exc()
            die()
    sys.stdout.flush()

if __name__ == '__main__':
    main()
