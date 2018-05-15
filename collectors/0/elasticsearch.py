#!/usr/bin/env python
# This file is part of tcollector.
# Copyright (C) 2011-2013  The tcollector Authors.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.  This program is distributed in the hope that it
# will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Lesser
# General Public License for more details.  You should have received a copy
# of the GNU Lesser General Public License along with this program.  If not,
# see <http://www.gnu.org/licenses/>.

"""ElasticSearch collector"""  # Because ES is cool, bonsai cool.
# Tested with ES 0.16.5, 0.17.x, 0.90.1 .
import base64
import re
import socket
import sys
import threading
import time

try:
    from urllib2 import urlopen, Request
    from urllib2 import HTTPError, URLError
except ImportError:
    from urllib.request import urlopen, Request
    from urllib.error import HTTPError, URLError

try:
    import json
except ImportError:
    json = None  # Handled gracefully in main.  Not available by default in <2.6

from collectors.lib import utils
from collectors.etc import elasticsearch_conf

COLLECTION_INTERVAL = 60  # seconds
DEFAULT_TIMEOUT = 10.0  # seconds

# regexes to separate differences in version numbers
PRE_VER1 = re.compile(r'^0\.')
VER1 = re.compile(r'^1\.')

STATUS_MAP = {
    "green": 0,
    "yellow": 1,
    "red": 2,
}

ROOTMETRIC = "elasticsearch"

REGISTERED_METRIC_TAGS = {
    ROOTMETRIC + ".node.ingest.pipelines": "pipeline",
    ROOTMETRIC + ".node.adaptive_selection": "asid",
    ROOTMETRIC + ".node.thread_pool": "threadpool"
}


class ESError(RuntimeError):
    """Exception raised if we don't get a 200 OK from ElasticSearch."""

    def __init__(self, resp):
        RuntimeError.__init__(self, str(resp))
        self.resp = resp


def _build_http_url(host, port, uri):
    if port == 443:
        protocol = "https"
    else:
        protocol = "http"
    return "%s://%s:%s%s" % (protocol, host, port, uri)


def _request(server, uri, json_in=True):
    utils.err("Requesting : %s" % uri)
    url = _build_http_url(server["host"], server["port"], uri)
    headers = server["headers"]
    req = Request(url)
    for key in headers.keys():
        req.add_header(key, headers[key])

    try:
        resp = urlopen(req, timeout=DEFAULT_TIMEOUT)
        resp_body = resp.read().decode("utf-8")
        if json_in:
            return json.loads(resp_body)
        else:
            return resp_body
    except HTTPError as err:
        utils.err(err)
    except URLError as err:
        utils.err(err)
        utils.err('We failed to reach a server.')


def cluster_health(server):
    return _request(server, "/_cluster/health")


def cluster_stats(server):
    return _request(server, "/_cluster/stats")


def cluster_master_node(server):
    return _request(server, "/_cat/master", json_in=False).split()[0]


def _index_stats(server):
    return _request(server, "/_all/_stats")


def node_status(server):
    return _request(server, "/")


def node_stats(server, version):
    # API changed in v1.0
    if PRE_VER1.match(version):
        url = "/_cluster/nodes/_local/stats"
    else:
        url = "/_nodes/stats"
    return _request(server, url)


def printmetric(metric, ts, value, tags):
    # Warning, this should be called inside a lock
    if tags:
        tags = " " + \
               " ".join("%s=%s" % (name.replace(" ", ""), value.replace(" ", "").replace(":", "-"))
                              for name, value in tags.items())
    else:
        tags = ""
    print("%s %d %s %s"
          % (metric, ts, value, tags))


def _traverse(metric, stats, timestamp, tags, check=True):
    """
       Recursively traverse the json tree and print out leaf numeric values
       Please make sure you call this inside a lock and don't add locking
       inside this function
    """
    # print metric,stats,ts,tags
    if isinstance(stats, dict):
        if "timestamp" in stats:
            timestamp = stats["timestamp"] / 1000  # ms -> s
        for key in list(stats.keys()):
            if key != "timestamp":
                if metric in REGISTERED_METRIC_TAGS:
                    if check:
                        registered_tags = tags.copy()
                        registered_tags[REGISTERED_METRIC_TAGS.get(metric)] = key
                        _traverse(metric, stats[key], timestamp, registered_tags, False)
                    else:
                        _traverse(metric + "." + key, stats[key], timestamp, tags)
                else:
                    _traverse(metric + "." + key, stats[key], timestamp, tags)
    if isinstance(stats, (list, set, tuple)):
        count = 0
        for value in stats:
            _traverse(metric + "." + str(count), value, timestamp, tags)
            count += 1
    if utils.is_numeric(stats) and not isinstance(stats, bool):
        if isinstance(stats, int):
            stats = int(stats)
        printmetric(metric, timestamp, stats, tags)
    return


def _collect_indices_total(metric, stats, tags, lock):
    ts = int(time.time())
    with lock:
        _traverse(metric, stats, ts, tags)


def _collect_indices_stats(metric, index_stats, tags, lock):
    ts = int(time.time())
    with lock:
        _traverse(metric, index_stats, ts, tags)


def _collect_indices(server, metric, tags, lock):
    index_stats = _index_stats(server)
    total_stats = index_stats["_all"]
    _collect_indices_total(metric + ".indices", total_stats, tags, lock)

    indices_stats = index_stats["indices"]
    while indices_stats:
        index_id, stats = indices_stats.popitem()
        index_tags = {"cluster": tags["cluster"], "index": index_id}
        _collect_indices_stats(metric + ".indices.byindex", stats, index_tags, lock)


def _collect_master(server, metric, tags, lock):
    ts = int(time.time())
    chealth = cluster_health(server)
    if "status" in chealth:
        with lock:
            printmetric(metric + ".cluster.status", ts,
                        STATUS_MAP.get(chealth["status"], -1), tags)
    with lock:
        _traverse(metric + ".cluster", chealth, ts, tags)

    ts = int(time.time())  # In case last call took a while.
    cstats = cluster_stats(server)
    with lock:
        _traverse(metric + ".cluster", cstats, ts, tags)


def _collect_server(server, version, lock):
    ts = int(time.time())
    nstats = node_stats(server, version)
    cluster_name = nstats["cluster_name"]
    _collect_cluster_stats(cluster_name, lock, ROOTMETRIC, server)
    while nstats["nodes"]:
        nodeid, n_stats = nstats["nodes"].popitem()
        node_name = n_stats["name"]
        tags = {"cluster": cluster_name, "node": node_name, "nodeid": nodeid}
        with lock:
            _traverse(ROOTMETRIC + ".node", n_stats, ts, tags)


def _collect_cluster_stats(cluster_name, lock, root_metric, server):
    cluster_tags = {"cluster": cluster_name}
    _collect_master(server, root_metric, cluster_tags, lock)
    _collect_indices(server, root_metric, cluster_tags, lock)


def _get_live_servers():
    servers = []
    for conf in elasticsearch_conf.get_servers():
        host = conf[0]
        port = conf[1]
        if len(conf) == 4:
            user = conf[2]
            password = conf[3]
            user_passwd = (user + ":" + password).encode("utf-8")
            auth_header = base64.b64encode(user_passwd)
            headers = {'Authorization': 'Basic %s' % auth_header.decode("ascii")}
        else:
            headers = {}

        server = {"host": host, "port": port, "headers": headers}
        status = node_status(server)
        if status:
            servers.append(server)
    return servers


def main(argv):
    utils.drop_privileges()
    socket.setdefaulttimeout(DEFAULT_TIMEOUT)

    if json is None:
        utils.err("This collector requires the `json' Python module.")
        return 1

    servers = _get_live_servers()

    if len(servers) == 0:
        return 13  # No ES running, ask tcollector to not respawn us.

    lock = threading.Lock()
    while True:
        threads = []
        ts0 = int(time.time())
        utils.err("Fetching elasticsearch metrics")
        for server in servers:
            status = node_status(server)
            version = status["version"]["number"]
            t = threading.Thread(target=_collect_server, args=(server, version, lock))
            t.start()
            threads.append(t)
        for thread in threads:
            thread.join(DEFAULT_TIMEOUT)

        utils.err("Done fetching elasticsearch metrics in [%d]s " % (int(time.time()) - ts0))
        sys.stdout.flush()
        time.sleep(COLLECTION_INTERVAL)


if __name__ == "__main__":
    utils.err(sys.version)
    sys.exit(main(sys.argv))
