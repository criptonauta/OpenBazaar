import logging


class PacketSender:

    def __init__(self, socket, hostname, port, transport):
        assert socket, 'No socket'

        self._socket = socket
        self._address = hostname
        self._port = int(port)
        self._transport = transport
        self._src_port = transport.port

        self.log = logging.getLogger(
            '%s' % (self.__class__.__name__)
        )

        self.log.info('Init PacketSender')

    def send(self, packet):
        send_buffer = packet.to_buffer(self._transport.guid,
                                       self._transport.pubkey,
                                       self._transport.hostname,
                                       self._src_port,
                                       self._transport.nickname)
        self.log.debug('About to send buffer: [%s] to %s:%s', send_buffer, self._address, self._port)
        self._socket.sendto(send_buffer, (self._address, self._port))
