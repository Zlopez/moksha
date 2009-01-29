# This file is part of Moksha.
#
# Moksha is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Moksha is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Moksha.  If not, see <http://www.gnu.org/licenses/>.
#
# Copyright 2008, Red Hat, Inc.
# Authors: Luke Macken <lmacken@redhat.com>

from moksha.hub.reactor import reactor

import os
import sys
import signal
import pkg_resources
import logging

from tg import config
from orbited import json
from threading import Thread
from collections import defaultdict
from paste.deploy import appconfig

from moksha.lib.helpers import trace
from moksha.hub.amqp import AMQPHub
from moksha.hub.stomp import StompHub

log = logging.getLogger('moksha.hub')

class MokshaHub(StompHub, AMQPHub):

    topics = None # {topic_name: [callback,]}

    def __init__(self, topics=None):
        self.amqp_broker = config.get('amqp_broker', None)
        self.stomp_broker = config.get('stomp_broker', None)

        self.topics = defaultdict(list)
        if topics:
            for topic, callbacks in topics.iteritems():
                if not isinstance(callbacks, list):
                    callbacks = [callbacks]
                for callback in callbacks:
                    self.topics[topic].append(callback)

        if self.amqp_broker:
            log.info('Initializing AMQP support')
            AMQPHub.__init__(self, self.amqp_broker)

        if self.stomp_broker:
            log.info('Initializing STOMP support')
            StompHub.__init__(self, self.stomp_broker,
                              port=config.get('stomp_port', 61613),
                              username=config.get('stomp_user', 'guest'),
                              password=config.get('stomp_pass', 'guest'),
                              topics=self.topics.keys())

    def send_message(self, topic, message, jsonify=True):
        """ Send a message to a specific topic.

        :topic: The stop to send the message to
        :message: The message body.  Can be a string, list, or dict.
        :jsonify: To automatically encode non-strings to JSON

        """
        if jsonify and not isinstance(message, basestring):
            message = json.encode(message)
        if self.amqp_broker:
            AMQPHub.send_message(self, topic, message, routing_key=topic)
        elif self.stomp_broker:
            StompHub.send_message(self, topic, message)

    def close(self):
        if self.amqp_broker:
            try:
                AMQPHub.close(self)
            except Exception, e:
                log.warning('Exception when closing AMQPHub: %s' % str(e))

    def watch_topic(self, topic, callback):
        """
        This method will cause the specified `callback` to be executed with
        each message that goes through a given topic.
        """
        if len(self.topics[topic]) == 0:
            if self.stomp_broker:
                self.subscribe(topic)
        self.topics[topic].append(callback)

    def consume_amqp_message(self, message):
        self.message_accept(message)
        topic = message.headers[0]['routing_key']
        try:
            body = json.decode(message.body)
        except Exception, e:
            log.warning('Cannot decode message from JSON: %s' % e)
            body = message.body
        if self.stomp_broker:
            StompHub.send_message(self, topic.encode('utf8'),
                                  message.body.encode('utf8'))

    def consume_stomp_message(self, message):
        topic = message['headers'].get('destination')
        if not topic:
            return
        try:
            body = json.decode(message['body'])
        except Exception, e:
            log.warning('Cannot decode message from JSON: %s' % e)
            body = message['body']

        # feed all of our consumers
        for callback in self.topics.get(topic, []):
            Thread(target=callback, args=[body]).start()


class CentralMokshaHub(MokshaHub):
    """
    The Moksha Hub is responsible for initializing all of the Hooks,
    AMQP queues, exchanges, etc.
    """
    data_streams = None # [<DataStream>,]

    def __init__(self):
        self.__init_consumers()

        MokshaHub.__init__(self, topics=self.topics)

        if self.amqp_broker:
            self.__init_amqp()

        self.__run_consumers()
        self.__init_data_streams()

    def __init_amqp(self):
        log.debug("Initializing local AMQP queue...")
        self.server_queue_name = 'moksha_hub_' + self.session.name
        self.queue_declare(queue=self.server_queue_name, exclusive=True)
        self.exchange_bind(self.server_queue_name) 
        self.local_queue_name = 'moksha_hub'
        self.local_queue = self.session.incoming(self.local_queue_name)
        self.message_subscribe(queue=self.server_queue_name,
                               destination=self.local_queue_name)
        self.local_queue.start()
        self.local_queue.listen(self.consume_amqp_message)

    def __init_consumers(self):
        """ Initialize all Moksha Consumer objects """
        log.info('Loading Moksha Consumers')
        for consumer in pkg_resources.iter_entry_points('moksha.consumer'):
            c_class = consumer.load()
            log.debug("%s consumer is watching the %r topic" % (
                      c_class.__name__, c_class.topic))
            self.topics[c_class.topic].append(c_class)

    def __run_consumers(self):
        """ Instantiate the consumers """
        for topic in self.topics:
            for i, consumer in enumerate(self.topics[topic]):
                c = consumer()
                self.topics[topic][i] = c.consume

    def __init_data_streams(self):
        """ Initialize all data streams """
        self.data_streams = []
        for stream in pkg_resources.iter_entry_points('moksha.stream'):
            stream_class = stream.load()
            log.info('Loading %s data stream' % stream_class.__name__)
            stream_obj = stream_class()
            self.data_streams.append(stream_obj)

    @trace
    def create_topic(self, topic):
        if self.amqp_broker:
            AMQPHub.create_queue(topic)

        # @@ remove this when we keep track of this in a DB
        if topic not in self.topics:
            self.topics[topic] = []

    def stop(self):
        log.debug("Stopping the CentralMokshaHub")
        MokshaHub.close(self)
        if self.data_streams:
            for stream in self.data_streams:
                log.debug("Stopping data stream %s" % stream)
                stream.stop()


def setup_logger(verbose):
    global log
    sh = logging.StreamHandler()
    level = verbose and logging.DEBUG or logging.INFO
    log.setLevel(level)
    sh.setLevel(level)
    format = logging.Formatter('[moksha.hub] %(levelname)s %(asctime)s %(message)s')
    sh.setFormatter(format)
    log.addHandler(sh)


def main():
    """ The main MokshaHub method """
    cfgfile = 'development.ini'
    if os.path.isfile('production.ini'):
        cfgfile= 'production.ini'
    cfg = appconfig('config:' + os.path.abspath(cfgfile))
    config.update(cfg)

    hub = CentralMokshaHub()

    def handle_signal(signum, stackframe):
        from moksha.hub.reactor import reactor
        if signum in [signal.SIGHUP, signal.SIGINT]:
            hub.stop()
            reactor.stop()

    signal.signal(signal.SIGHUP, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    log.info("Running the MokshaHub reactor")
    reactor.run(installSignalHandlers=False)
    log.info("MokshaHub reactor stopped")


if __name__ == '__main__':
    setup_logger('-v' in sys.argv or '--verbose' in sys.argv)
    main()
