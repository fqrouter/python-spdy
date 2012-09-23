#!/usr/bin/env python2
# coding: utf-8
# Very basic TLS Client using tlslite (0.4.1 library, which supports NPN).
# Python 2.7+, does NOT work in Python 3.x.
# https://groups.google.com/d/msg/spdy-dev/gY66X7Ew0aA/HbN_lmUGT5kJ
# Author: Marcelo Fernández
# marcelo.fidel.fernandez@gmail.com / mail@marcelofernandez.info

import sys
import socket
from tlslite.api import TLSConnection
from io import BytesIO
import gzip
from spdy.context import Context, CLIENT, SpdyProtocolError
from spdy.frames import SynStream, Ping, Goaway, FLAG_FIN

DEFAULT_HOST = 'www.google.com'
DEFAULT_PORT = 443
SPDY_VERSION = 2

def str2hexa(string, columns=4):
    """ Helper function to print hexadecimal bytestrings.
        Columns controls how many columns (bytes) are printer before end of line.
        If columns == 0, then only add EoL at the end.

        Example:
            In [5]: str2hexa('abc\n')
            Out[5]: '0x61 0x62 0x63 0x0A'

        TODO: Doesn't work in python 3, remedy this
    """
    hexa =''
    if columns < 1: columns = len(string)
    for i, s in enumerate(string, 1):
        hexa += '0x%02x' % ord(s) + ' '
        if i % columns == 0:
            hexa = hexa[:-1] + '\n'
    return hexa[:-1]

def parse_args():
    len_args = len(sys.argv)
    if len_args == 2:
        host = sys.argv[1]
        port = DEFAULT_PORT
    elif len_args > 2:
        host = sys.argv[1]
        try:
            port = int(sys.argv[2])
        except ValueError:
            port = DEFAULT_PORT
    else:
        host = DEFAULT_HOST
        port = DEFAULT_PORT
    return (host, port)

def ping_test(spdy_ctx):
    """ Just Pings the server through a SPDY Ping Frame """
    ping_frame = Ping(spdy_ctx.next_ping_id, version=SPDY_VERSION)
    print('>>', ping_frame)
    spdy_ctx.put_frame(ping_frame)

def get_headers(version, host, path):
    # TODO: Review gzip content-type
    if version == 2:
        return {'method' : 'GET',
                'url'    : path,
                'version': 'HTTP/1.1',
                'host'   : host,
                'scheme' : 'https',
                }
    else:
        return {':method' : 'GET',
                ':path'   : path,
                ':version': 'HTTP/1.1',
                ':host'   : host,
                ':scheme' : 'https',
                } 

def get_page(spdy_ctx, host, path='/'):
    syn_frame = SynStream(stream_id=spdy_ctx.next_stream_id,
                      flags=FLAG_FIN, 
                      headers=get_headers(SPDY_VERSION, host, path), 
                      version=SPDY_VERSION)
    print('>>', syn_frame, 'Headers:', syn_frame.headers)
    spdy_ctx.put_frame(syn_frame)

def get_frame(spdy_ctx):
    try:
        return spdy_ctx.get_frame()
    except SpdyProtocolError as e:
        print ('error parsing frame: %s' % str(e))

if __name__ == '__main__':
    host, port = parse_args()

    print('Trying to connect to %s:%i' % (host, port))

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    connection = TLSConnection(sock)

    if SPDY_VERSION == 2:
        connection.handshakeClientCert(nextProtos=["spdy/2"])
    else:
        connection.handshakeClientCert(nextProtos=["spdy/3"])

    spdy_ctx = Context(CLIENT, version=SPDY_VERSION)

    ping_test(spdy_ctx)
    get_page(spdy_ctx, host)

    out = spdy_ctx.outgoing()
    #print str2hexa(str(out))
    connection.write(out)
    file_out = open('/tmp/spdyout.txt', 'wb')
    goaway = False
    content_type_id = {}
    while not goaway:
        answer = connection.read() # Blocking
        #print '<<\n', str2hexa(answer)
        spdy_ctx.incoming(answer)
        frame = get_frame(spdy_ctx)
        while frame:
            if hasattr(frame, 'headers'):
                print ('<<', frame, 'Headers:', frame.headers)
                content_type_id[frame.stream_id] = frame.headers.get('content-encoding')                      
            elif hasattr(frame, 'data'):
                data = frame.data
                # Handle gzipped data
                if content_type_id[frame.stream_id] == 'gzip':
                    iodata = BytesIO(bytes(data))
                    data = gzip.GzipFile(fileobj=iodata).read() 
                print ('<<', frame, 'Data:', data[:512].decode('utf-8', 'ignore'))
                file_out.write(data)
                file_out.flush()
            else:
                print ('<<', frame)
            frame = get_frame(spdy_ctx)
            if isinstance(frame, Goaway):
                goaway = True
