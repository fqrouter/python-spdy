# coding: utf-8
from spdy.frames import *
from c_zlib import compress, decompress, HEADER_ZLIB_DICT_2
from bitarray import bitarray
import struct

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

class Context(object):
	def __init__(self, side, version=2):
		if side not in (SERVER, CLIENT):
			raise TypeError("side must be SERVER or CLIENT")

		if not version in VERSIONS:
			raise NotImplementedError()
		self.version = version
		self.frame_queue = []
		self.input_buffer = bytearray()

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
		#frame, bytes_parsed = self._parse_frame(bytes(self.input_buffer))
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
		chunk = decompress(compressed_data, dictionary=HEADER_ZLIB_DICT_2)
		
		length_size = 2 if version == 2 else 4
		length_fmt = '>H' if length_size == 2 else '>L'
		headers = {}

		#first two bytes: number of pairs
		#num_values = int.from_bytes(chunk[0:length_size], 'big')
		num_values = struct.unpack(length_fmt, chunk[0:length_size])[0]

		#after that...
		cursor = length_size
		for _ in range(num_values):
			#two/four bytes: length of name
			#name_length = int.from_bytes(chunk[cursor:cursor+length_size], 'big')
			name_length = struct.unpack(length_fmt, chunk[cursor:cursor+length_size])[0]
			cursor += length_size

			#next name_length bytes: name
			name = chunk[cursor:cursor+name_length].decode('UTF-8')
			cursor += name_length

			#two/four bytes: length of value
			#value_length = int.from_bytes(chunk[cursor:cursor+length_size], 'big')
			value_length = struct.unpack(length_fmt, chunk[cursor:cursor+length_size])[0]
			cursor += length_size

			#next value_length bytes: value
			value = chunk[cursor:cursor+value_length].decode('UTF-8')
			cursor += value_length

			if name_length == 0 or value_length == 0:
				raise SpdyProtocolError("zero-length name or value in n/v block")
			if name in headers:
				raise SpdyProtocolError("duplicate name in n/v block")
			headers[name] = value

		return headers

	def _parse_settings_id_values(self, number_of_entries, data):
		id_value_pairs = {}

		cursor = 0
		for _ in range(number_of_entries):
			# 3B = ID
			#id = int.from_bytes(data[cursor:cursor+3], 'little')
			id = struct.unpack('<L', data[cursor:cursor+3] + '\x00')[0]
			cursor += 3
			# 1B = ID_Flag
			#id_flag = int.from_bytes(data[cursor:cursor+1], 'big')
			id_flag = struct.unpack('>B', data[cursor:cursor+1])[0]
			cursor += 1
			# 4B = Value
			#value = int.from_bytes(data[cursor:cursor+4], 'big')
			value = struct.unpack('>L', data[cursor:cursor+4])[0]
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
			#spdy_version = int.from_bytes(chunk[0:2], 'big') & _last_15_bits
			spdy_version = struct.unpack('>H', str(chunk[0:2]))[0] & _last_15_bits
			if spdy_version != self.version:
				raise SpdyProtocolError("incorrect SPDY version")

			#third and fourth byte: frame type
			#frame_type = int.from_bytes(chunk[2:4], 'big')
			frame_type = struct.unpack('>H', str(chunk[2:4]))[0]
			if not frame_type in FRAME_TYPES:
				raise SpdyProtocolError("invalid frame type: {0}".format(frame_type))

			#fifth byte: flags
			flags = chunk[4]

			#sixth, seventh and eighth bytes: length
			#length = int.from_bytes(chunk[5:8], 'big')
			length = struct.unpack('>L', '\x00' + str(chunk[5:8]))[0]
			frame_length = length + 8
			if len(chunk) < frame_length:
				return (None, 0)

			#the rest is data
			data = str(chunk[8:frame_length])

			bits = bitarray()
			bits.frombytes(data)
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
					args[key] = self._parse_settings_id_values(args['number_of_entries'], \
															value.tobytes())
				else:
					#we have to pad values on the left, because bitarray will assume
					#that you want it padded from the right
					gap = len(value) % 8
					if gap:
						zeroes = bitarray(8 - gap)
						zeroes.setall(False)
						value = zeroes + value
					#args[key] = int.from_bytes(value.tobytes(), 'big')
					# TODO: Ver si se puede mejorar esta conversión
					args[key] = int(value.tobytes().encode('hex'), 16)

				if num_bits == -1:
					break

			frame = frame_cls(**args)

		else: #data frame
			#first four bytes, except the first bit: stream_id
			#stream_id = int.from_bytes(_last_31_bits(chunk[0:4]), 'big')
			stream_id = struct.unpack('>L', str(chunk[0:4]))[0] & _last_31_bits

			#fifth byte: flags
			flags = chunk[4]

			#sixth, seventh and eight bytes: length
			#length = int.from_bytes(chunk[5:8], 'big')
			length = struct.unpack('>L', '\x00' + str(chunk[5:8]))[0]
			frame_length = 8 + length
			if len(chunk) < frame_length:
				return (0, None)

			data = str(chunk[8:frame_length])
			frame = DataFrame(stream_id, data)

		return (frame, frame_length)

	def _encode_header_chunk(self, headers):
		chunk = bytearray()

		#first two bytes: number of pairs
		#chunk.extend(len(headers).to_bytes(2, 'big'))
		chunk.extend(struct.pack('>H', len(headers)))

		#after that...
		for name, value in sorted(headers.items()):
			#name = bytes(name, 'UTF-8')
			name = name.encode('UTF-8')

			#value = bytes(value, 'UTF-8')
			value = value.encode('UTF-8')

			#two bytes: length of name
			#chunk.extend(len(name).to_bytes(2, 'big'))
			chunk.extend(struct.pack('>H', len(name)))

			#next name_length bytes: name
			chunk.extend(name)

			#two bytes: length of value
			#chunk.extend(len(value).to_bytes(2, 'big'))
			chunk.extend(struct.pack('>H', len(value)))

			#next value_length bytes: value
			chunk.extend(value)

		compressed_headers = compress(str(chunk), level=6, dictionary=HEADER_ZLIB_DICT_2)
		return compressed_headers[:-1] # Don't know why -1

	def _encode_settings_id_values(self, id_values_dict):
		chunk = bytearray()

		for id, (id_flag, value) in id_values_dict.items():
			# 3B = ID
			#chunk.extend(id.to_bytes(3, 'little'))
			chunk.extend(struct.pack('<L', id)[:-1])
			# 1B = ID_Flag
			#chunk.extend(id_flag.to_bytes(1, 'big'))
			chunk.extend(struct.pack('>H', id_flag)[1:])
			# 4B = Value
			#chunk.extend(value.to_bytes(4, 'big'))
			chunk.extend(struct.pack('>L', value))

		#return bytes(chunk)
		return chunk

	def _encode_frame(self, frame):
		out = bytearray()

		if frame.is_control:
			#first two bytes: version
			#out.extend(frame.version.to_bytes(2, 'big'))
			out.extend(struct.pack('>H', frame.version))

			#set the first bit to control
			out[0] = out[0] | _first_bit

			#third and fourth: frame type
			#out.extend(frame.frame_type.to_bytes(2, 'big'))
			out.extend(struct.pack('>H', frame.frame_type))

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
					chunk.frombytes(self._encode_header_chunk(value))
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
			#out.extend(len(data).to_bytes(3, 'big'))
			out.extend(struct.pack('>L', len(data))[1:])
			# the rest is data
			out.extend(data)

		else: #data frame

			#first four bytes: stream_id
			#out.extend(frame.stream_id.to_bytes(4, 'big'))
			out.extend(struct.pack('>L', frame.stream_id))

			#fifth: flags
			out.append(frame.flags)

			#sixth, seventh and eighth bytes: length
			data_length = len(frame.data)
			#out.extend(data_length.to_bytes(3, 'big'))
			out.extend(struct.pack('>L', data_length)[1:])

			#rest is data
			out.extend(frame.data)

		return out

