#!/usr/bin/env python3.3
# You can try this example with a spdyclient test or Mozilla Firefox.
import socket
import ssl
from spdy.context import Context, SERVER 
from spdy.frames import SynStream, SynReply, Ping, Goaway, DataFrame

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
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
    if isinstance(f, Ping):
        ping = Ping(f.uniq_id)
        conn.put_frame(ping)
        print(str(ping) + ", SAYS SERVER")
    elif isinstance(f, SynStream):
        resp = SynReply(f.stream_id, {'status': '200 OK', 'version': 'HTTP/1.1'}, flags=0)
        conn.put_frame(resp)
        print(str(resp) + ", SAYS SERVER")
        data = DataFrame(f.stream_id, b"hello, world!", flags=1)
        conn.put_frame(data)
        print(str(data) + ", SAYS SERVER")
        goaway = Goaway(f.stream_id)
        conn.put_frame(goaway)
        print(str(goaway) + ", SAYS SERVER")
    elif isinstance(f, Goaway):
        return True

try:
    print ('Running one-time one-client SPDY Server...')
    client_socket, address = server.accept()
    ss = ctx.wrap_socket(client_socket, server_side=True)
    conn = Context(SERVER)
    finish = False
    while not finish:
        d = ss.recv(1024)
        conn.incoming(d)
        frame = conn.get_frame()
        if frame:
            finish = handle_frame(conn, frame)
            outgoing = conn.outgoing()
            if outgoing:
                ss.sendall(outgoing)
        

except Exception as exc:
    print(exc)
finally:
    server.close()
