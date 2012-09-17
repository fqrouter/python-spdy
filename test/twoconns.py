#!/usr/bin/env python
# coding: utf-8

from spdy.context import Context, CLIENT, SERVER
from spdy.frames import SynStream, SynReply

server = Context(SERVER)
client = Context(CLIENT)

frame = SynStream(stream_id=client.next_stream_id, headers={'dood': 'balls', 'stuff': 'otherstuff'})
client.put_frame(frame)
chunk = client.outgoing()

server.incoming(chunk)
frame2 = server.get_frame()
print(frame2)
print(frame2.headers)

frame3 = SynReply(stream_id=server.next_stream_id, headers={'got it': 'yup', 'roger': 'roger'})
server.put_frame(frame3)
chunk2 = server.outgoing()

client.incoming(chunk2)
frame4 = client.get_frame()
print(frame4.headers)
