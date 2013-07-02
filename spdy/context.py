# coding: utf-8
from sys import version_info
from bitarray import bitarray
from spdy.c_zlib import Inflater, Deflater, ZLIB_DICT_V2, ZLIB_DICT_V3
from spdy.frames import Frame, DataFrame, DEFAULT_VERSION, VERSIONS, FRAME_TYPES

SERVER = 'SERVER'
CLIENT = 'CLIENT'

class SpdyProtocolError(Exception):
    pass

def _bitmask(length, split, mask=0):
    invert = 1 if mask == 0 else 0
    b = str(mask)*split + str(invert)*(length-split)
    return int(b, 2)

_first_bit = _bitmask(8, 1, 1)
_last_15_bits = _bitmask(16, 1, 0)
_last_31_bits = _bitmask(32, 1, 0)

if version_info[0:2] < (3,2):
    import struct
    def get_struct_params(str_length, byte_order):
        """ Guess pack integer format, for unsigned 1 to 4-Byte int byte-strings """
        pad_before, pad_after = 0, 0
        endianess = '>' if byte_order == 'big' else '<'
        if str_length == 1:
            int_format = 'B'
        elif str_length == 2:
            int_format = 'H'
        elif str_length <= 4:
            int_format = 'L'
            if str_length == 3:
                if endianess == '>':
                    pad_before = 1
                else:
                    pad_after = 1
        else:
            raise ValueError('String length exceeds 4 Bytes long')
        return (endianess + int_format, pad_before, pad_after)

    def get_int_from_stream(stream, byte_order):
        length_fmt, pad_before, pad_after = get_struct_params(len(stream), 
                                                              byte_order)
        stream = str(stream)
        return struct.unpack(length_fmt, '\x00' * pad_before + stream + 
                                         '\x00' * pad_after)[0]
    
    def get_stream_from_int(int_value, length, byte_order):
        length_fmt, pad_before, pad_after = get_struct_params(length, byte_order)
        packed_int = struct.pack(length_fmt, int_value)
        if pad_before > 0:
            packed_int = packed_int[pad_before:]
        if pad_after > 0:
            packed_int = packed_int[:-pad_after]
        return packed_int
else:
    def get_int_from_stream(stream, byte_order):
        return int.from_bytes(stream, byte_order)
    def get_stream_from_int(int_value, length, byte_order):
        return int_value.to_bytes(length, byte_order)


class Context(object):
    def __init__(self, side, version=DEFAULT_VERSION):
        if side not in (SERVER, CLIENT):
            raise TypeError("side must be SERVER or CLIENT")

        if not version in VERSIONS:
            raise NotImplementedError()
        self.version = version
        self.frame_queue = []
        self.input_buffer = bytearray()
        self.inflater = Inflater(version)
        self.deflater = Deflater(version)

        if side == SERVER:
            self._stream_id = 2
            self._ping_id = 2
        else:
            self._stream_id = 1
            self._ping_id = 1

    @property
    def next_stream_id(self):
        sid = self._stream_id
        self._stream_id += 2
        return sid

    @property
    def next_ping_id(self):
        pid = self._ping_id
        self._ping_id += 2
        return pid

    def incoming(self, chunk):
        self.input_buffer.extend(chunk)

    def get_frame(self):
        frame, bytes_parsed = self._parse_frame(self.input_buffer)
        if bytes_parsed:
            self.input_buffer = self.input_buffer[bytes_parsed:]
        return frame

    def put_frame(self, frame):
        if not isinstance(frame, Frame):
            raise TypeError("frame must be a valid Frame object")
        self.frame_queue.append(frame)

    def outgoing(self):
        out = bytearray()
        while len(self.frame_queue) > 0:
            frame = self.frame_queue.pop(0)
            out.extend(self._encode_frame(frame))
        return out

    def _parse_header_chunk(self, compressed_data, version):
        # Zlib dictionary selection
        chunk = self.inflater.decompress(compressed_data)
        
        length_size = 2 if version == 2 else 4
        headers = {}

        #first two bytes: number of pairs
        num_values = get_int_from_stream(chunk[0:length_size], 'big')

        #after that...
        cursor = length_size
        for _ in range(num_values):
            #two/four bytes: length of name
            name_length = get_int_from_stream(chunk[cursor:cursor+length_size], 'big')
            cursor += length_size

            #next name_length bytes: name
            name = chunk[cursor:cursor+name_length].decode('UTF-8')
            cursor += name_length

            #two/four bytes: length of value
            value_length = get_int_from_stream(chunk[cursor:cursor+length_size], 'big')
            cursor += length_size

            #next value_length bytes: value
            value = chunk[cursor:cursor+value_length].decode('UTF-8')
            cursor += value_length

            if name_length == 0 or value_length == 0:
                continue
            if name in headers:
                raise SpdyProtocolError("duplicate name in n/v block")
            headers[name] = value

        return headers

    def _parse_settings_id_values_v2(self, number_of_entries, data):
        id_value_pairs = {}
        cursor = 0
        for _ in range(number_of_entries):
            # 3B = ID
            id = get_int_from_stream(data[cursor:cursor+3], 'little')
            cursor += 3
            # 1B = ID_Flag
            id_flag = get_int_from_stream(data[cursor:cursor+1], 'big')
            cursor += 1
            # 4B = Value
            value = get_int_from_stream(data[cursor:cursor+4], 'big')
            cursor += 4
            id_value_pairs[id] = (id_flag, value)
        return id_value_pairs

    def _parse_settings_id_values_v3(self, number_of_entries, data):
        id_value_pairs = {}
        cursor = 0
        for _ in range(number_of_entries):
            # 1B = ID_Flag
            id_flag = get_int_from_stream(data[cursor:cursor+1], 'big')
            cursor += 1
            # 3B = ID
            id = get_int_from_stream(data[cursor:cursor+3], 'big')
            cursor += 3
            # 4B = Value
            value = get_int_from_stream(data[cursor:cursor+4], 'big')
            cursor += 4
            id_value_pairs[id] = (id_flag, value)
        return id_value_pairs

    def _parse_frame(self, chunk):
        if len(chunk) < 8:
            return (None, 0)

        #first bit: control or data frame?
        control_frame = (chunk[0] & _first_bit == _first_bit)

        if control_frame:
            #second byte (and rest of first, after the first bit): spdy version
            spdy_version = get_int_from_stream(chunk[0:2], 'big') & _last_15_bits
            if spdy_version != self.version:
                raise SpdyProtocolError("incorrect SPDY version")

            #third and fourth byte: frame type
            frame_type = get_int_from_stream(chunk[2:4], 'big')
            if not frame_type in FRAME_TYPES:
                raise SpdyProtocolError("invalid frame type: {0}".format(frame_type))

            #fifth byte: flags
            flags = chunk[4]

            #sixth, seventh and eighth bytes: length
            length = get_int_from_stream(chunk[5:8], 'big')
            frame_length = length + 8
            if len(chunk) < frame_length:
                return (None, 0)

            #the rest is data
            data = chunk[8:frame_length]

            bits = bitarray()
            bits.frombytes(bytes(data))
            frame_cls = FRAME_TYPES[frame_type]

            args = {
                'version': spdy_version,
                'flags': flags
            }

            for key, num_bits in frame_cls.definition(spdy_version):
                if not key:
                    bits = bits[num_bits:]
                    continue

                if num_bits == -1:
                    value = bits
                else:
                    value = bits[:num_bits]
                    bits = bits[num_bits:]

                if key == 'headers': #headers are compressed
                    args[key] = self._parse_header_chunk(value.tobytes(), self.version)
                elif key == 'id_value_pairs':
                    if self.version == 2:
                        args[key] = self._parse_settings_id_values_v2(args['number_of_entries'], \
                                                            value.tobytes())
                    else:
                        args[key] = self._parse_settings_id_values_v3(args['number_of_entries'], \
                                                            value.tobytes())
                else:
                    #we have to pad values on the left, because bitarray will assume
                    #that you want it padded from the right
                    gap = len(value) % 8
                    if gap:
                        zeroes = bitarray(8 - gap)
                        zeroes.setall(False)
                        value = zeroes + value
                    args[key] = get_int_from_stream(value.tobytes(), 'big')

                if num_bits == -1:
                    break

            frame = frame_cls(**args)

        else: #data frame
            #first four bytes, except the first bit: stream_id
            stream_id = get_int_from_stream(chunk[0:4], 'big') & _last_31_bits

            #fifth byte: flags
            flags = chunk[4]

            #sixth, seventh and eight bytes: length
            length = get_int_from_stream(chunk[5:8], 'big')
            frame_length = 8 + length
            if len(chunk) < frame_length:
                return (0, None)

            data = chunk[8:frame_length]
            frame = DataFrame(stream_id, data)

        return (frame, frame_length)

    def _encode_header_chunk(self, headers, version):
        chunk = bytearray()
        length_size = 2 if version == 2 else 4
        
        #first two bytes: number of pairs
        chunk.extend(get_stream_from_int(len(headers), length_size, 'big'))

        #after that...
        for name, value in headers.items():
            name = bytes(name.encode('utf-8'))
            value = bytes(value.encode('utf-8'))

            #two bytes: length of name
            chunk.extend(get_stream_from_int(len(name), length_size, 'big'))

            #next name_length bytes: name
            chunk.extend(name)

            #two bytes: length of value
            chunk.extend(get_stream_from_int(len(value), length_size, 'big'))

            #next value_length bytes: value
            chunk.extend(value)
            
        return self.deflater.compress(bytes(chunk))

    def _encode_settings_id_values_v2(self, id_values_dict):
        chunk = bytearray()
        for id, (id_flag, value) in id_values_dict.items():
            # 3B = ID
            chunk.extend(get_stream_from_int(id, 3, 'little'))
            # 1B = ID_Flag
            chunk.extend(get_stream_from_int(id_flag, 1, 'big'))
            # 4B = Value
            chunk.extend(get_stream_from_int(value, 4, 'big'))
        return bytes(chunk)

    def _encode_settings_id_values_v3(self, id_values_dict):
        chunk = bytearray()
        for id, (id_flag, value) in id_values_dict.items():
            # 1B = ID_Flag
            chunk.extend(get_stream_from_int(id_flag, 1, 'big'))
            # 3B = ID
            chunk.extend(get_stream_from_int(id, 3, 'big'))
            # 4B = Value
            chunk.extend(get_stream_from_int(value, 4, 'big'))
        return bytes(chunk)

    def _encode_frame(self, frame):
        out = bytearray()

        if frame.is_control:
            #first two bytes: version
            out.extend(get_stream_from_int(frame.version, 2, 'big'))

            #set the first bit to control
            out[0] = out[0] | _first_bit

            #third and fourth: frame type
            out.extend(get_stream_from_int(frame.frame_type, 2, 'big'))

            #fifth: flags
            out.append(frame.flags)

            bits = bitarray()
            for key, num_bits in frame.definition(self.version):

                if not key: # is False
                    zeroes = bitarray(num_bits)
                    zeroes.setall(False)
                    bits += zeroes
                    continue

                value = getattr(frame, key)
                if key == 'headers':
                    chunk = bitarray()
                    chunk.frombytes(self._encode_header_chunk(value, frame.version))
                elif key == 'id_value_pairs':
                    chunk = bitarray()
                    if frame.version == 2:
                        chunk_content = self._encode_settings_id_values_v2(value)
                    else:
                        chunk_content = self._encode_settings_id_values_v3(value)
                    chunk.frombytes(chunk_content)
                else:
                    chunk = bitarray(bin(value)[2:])
                    zeroes = bitarray(num_bits - len(chunk))
                    zeroes.setall(False)
                    chunk = zeroes + chunk #pad with zeroes

                bits += chunk
                if num_bits == -1:
                    break
            data = bits.tobytes()

            #sixth, seventh and eighth bytes: length
            out.extend(get_stream_from_int(len(data), 3, 'big'))
            # the rest is data
            out.extend(data)

        else: #data frame

            #first four bytes: stream_id
            out.extend(get_stream_from_int(frame.stream_id, 4, 'big'))

            #fifth: flags
            out.append(frame.flags)

            #sixth, seventh and eighth bytes: length
            data_length = len(frame.data)
            out.extend(get_stream_from_int(data_length, 3, 'big'))

            #rest is data
            out.extend(frame.data)

        return out
