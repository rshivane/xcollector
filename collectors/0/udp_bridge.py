#!/usr/bin/env python
# This file is part of tcollector.
# Copyright (C) 2013  The tcollector Authors.
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
"""Listens on a local UDP socket for incoming Metrics """

import socket
import sys
import threading
import time

try:
    from queue import Queue, Empty, Full
except ImportError:
    from Queue import Queue, Empty, Full

from collectors.lib import utils

try:
    from collectors.etc import udp_bridge_conf
except ImportError:
    udp_bridge_conf = None

HOST = '127.0.0.1'
PORT = 8953
SIZE = 8192

MAX_UNFLUSHED_DATA = 8192
MAX_PACKETS_IN_MEMORY = 100

ALIVE = True
FLUSH_BEFORE_EXIT = udp_bridge_conf and udp_bridge_conf.flushBeforeExit()


class ReaderQueue(Queue):

    def nput(self, value):
        try:
            self.put(value, False)
        except Full:
            utils.err("DROPPED LINES [%d] bytes" % len(value))
            return False
        return True


class SenderThread(threading.Thread):

    def __init__(self, readerq, flush_delay):
        super(SenderThread, self).__init__()
        self.readerq = readerq
        self.flush_delay = flush_delay

    def run(self):
        unflushed_data_len = 0
        flush_timeout = int(time.time())
        global ALIVE
        queue_is_empty = False
        while ALIVE or (FLUSH_BEFORE_EXIT and not queue_is_empty):
            try:
                data = self.readerq.get(True, 2)
                trace("DEQUEUED")
                print(data)
                trace("PRINTED")
                unflushed_data_len += len(data)
                queue_is_empty = False
            except Empty:
                queue_is_empty = True

            now = int(time.time())
            if unflushed_data_len > MAX_UNFLUSHED_DATA or now > flush_timeout:
                flush_timeout = now + self.flush_delay
                sys.stdout.flush()
                unflushed_data_len = 0

        trace("SENDER THREAD EXITING")


def trace(msg):
    # utils.err(msg)
    pass


def main():
    if not (udp_bridge_conf and udp_bridge_conf.enabled()):
        sys.exit(13)
    utils.drop_privileges()

    def removePut(line):
        if line.startswith('put '):
            return line[4:]
        else:
            return line

    try:
        if (udp_bridge_conf and udp_bridge_conf.usetcp()):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((HOST, PORT))
    except socket.error as msg:
        utils.err('could not open socket: %s' % msg)
        sys.exit(1)

    try:
        flush_delay = udp_bridge_conf.flush_delay()
    except AttributeError:
        flush_delay = 60

    global ALIVE
    readerq = ReaderQueue(MAX_PACKETS_IN_MEMORY)
    sender = SenderThread(readerq, flush_delay)
    sender.start()

    try:
        try:
            while ALIVE:
                data, address = sock.recvfrom(SIZE)
                if data:
                    trace("Read packet:")
                    lines = data.splitlines()
                    data = '\n'.join(map(removePut, lines))
                    trace(data)
                if not data:
                    utils.err("invalid data")
                    break
                readerq.nput(data)
                trace("ENQUEUED")

        except KeyboardInterrupt:
            utils.err("keyboard interrupt, exiting")
    finally:
        ALIVE = False
        sock.close()
        sender.join()
        trace("MAIN THREAD EXITING")


if __name__ == "__main__":
    main()

sys.exit(0)
