#!/usr/bin/env python3.3
import socket
import ssl
from spdy.context import Context, SERVER 
import spdy.frames

server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(('', 9599))
server.listen(5)

ctx = ssl.SSLContext(ssl.PROTOCOL_SSLv23)

# Forcing DES-CBC3-SHA for Wireshark+Spdyshark to be able to decrypt this
# http://code.google.com/p/spdyshark/
# http://japhr.blogspot.com/2011/05/ssl-that-can-be-sniffed-by-wireshark.html
ctx.set_ciphers('DES-CBC3-SHA')

ctx.load_cert_chain('server.crt', 'server.key')
ctx.set_npn_protocols(['spdy/2'])

def handle_frame(conn, f):
    print("CLIENT SAYS,", f)

    if isinstance(f, spdy.frames.Ping):
        ping = spdy.frames.Ping(f.uniq_id)
        conn.put_frame(ping)
        print(str(ping) + ", SAYS SERVER")

    elif isinstance(f, spdy.frames.SynStream):
        resp = spdy.frames.SynReply(f.stream_id, {'status': '200 OK', 'version': 'HTTP/1.1'}, flags=0)
        conn.put_frame(resp)
        print(str(resp) + ", SAYS SERVER")
        data = spdy.frames.DataFrame(f.stream_id, b"hello, world!", flags=1)
        conn.put_frame(data)
        print(str(data) + ", SAYS SERVER")

try:
    while True:
        try:
            print ('Running one-client SPDY Server...')
            sock, sockaddr = server.accept()
            ss = ctx.wrap_socket(sock, server_side=True)

            conn = Context(SERVER)

            while True:
                d = ss.recv(1024)
                conn.incoming(d)
                while True:
                    f = conn.get_frame()
                    if not f:
                        break
                    handle_frame(conn, f)

                outgoing = conn.outgoing()
                if outgoing:
                    ss.sendall(outgoing)

        except Exception as exc:
            print(exc)
            if not "EOF" in str(exc): raise
            continue

finally:
    server.close()
