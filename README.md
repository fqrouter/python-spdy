python-spdy
==========

python-spdy is a simple spdy parser/(de)muxer for Python 2.6 or newer. Python 3 is supported.

Usage
-----

	import spdy.context, spdy.frames
	
	#with an existing socket or something
	context = spdy.context.Context(side=spdy.context.SERVER, version=2)

	while True:
		data = sock.recv(1024)
		if not data:
			break

		context.incoming(data)

		while True:
			frame = context.get_frame()
			if not frame: 
				break
			
			if isinstance(frame, spdy.frames.Ping):
				pong = spdy.frames.Ping(frame.ping_id)
				context.put_frame(pong)
	
		outgoing = context.outgoing()
		if outgoing:
			sock.sendall(outgoing)	

Installation
------------

requires:

	pip install bitarray

then:
	
	python setup.py install

Note: To use this library for I/O networking, the SPDY protocol usually needs
      below an SSL layer with NPN (Next-Protocol Negotiation) support. 
      Python 3.3+ does support ssl.set_npn_protocols() call, only for 
      environments running OpenSSL 1.0.1+. 
      If you are not running Python 3.3+ over OpenSSL 1.0.1+, you can use 
      the tlslite module [1], from Python 2.6/2.7 instead. 
      However, the latest 0.4.1 version doesn't have a patch which includes
      support for Client NPN; you can find a patched tlslite 0.4.1 supporting
      Client NPN here [2]. 
      I've posted a pull request to the author, so I hope this issue will be 
      resolved soon in future tlslite release.
      Take a look at the /test directory for client and server examples.

[1] http://pypi.python.org/pypi/tlslite
[2] https://github.com/marcelofernandez/tlslite
