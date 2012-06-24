# coding: utf-8
""" Dummy SPDY Classes testing and examples, no network involved """

import spdy
from spdy.frames import *

def str2hexa(string):
    """ Helper function to print hexadecimal bytestrings
        Example:
            In [5]: str2hexa('abc\n')
            Out[5]: '0x61 0x62 0x63 0x0A'

        TODO: Doesn't work in python 2, remedy this
    """
    hexa=''
    for s in string:
        hexa += '0x%02x' % s + ' '
    return hexa.rstrip()

def print_encoded_frame(frame):
    for i in range(0, len(frame), 4):
        print(str2hexa(frame[i:i+4]))

if __name__ == '__main__':
    ctx = spdy.Context(spdy.context.CLIENT)
    frame = SynStream(1, {})
    print ('SYN Frame')
    print_encoded_frame(ctx._encode_frame(frame))

    print ('SETTINGS Frame')
    frame = Settings(2, {UPLOAD_BANDWIDTH: (ID_FLAG_PERSIST_NONE, 60),
                         DOWNLOAD_BANDWIDTH : (ID_FLAG_PERSIST_NONE, 128)})
    byte_frame = ctx._encode_frame(frame)
    print_encoded_frame(byte_frame)

    frame2 = ctx._parse_frame(bytes(byte_frame))[0]
    print(frame2)