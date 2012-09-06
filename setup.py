from distutils.core import setup
# Forked from python-spdy package from Colin Marc - colinmarc@gmail.com
# http://github.com/colinmarc/python-spdy
setup(
	name='spdy',
	version='0.2',
	description='A parser/muxer/demuxer for spdy frames',
	author='Marcelo Fernandez',
	author_email='marcelo.fidel.fernandez@gmail.com',
	url='http//www.github.com/marcelofernandez/python-spdy',
	packages=['spdy'],
	package_dir={'spdy': 'spdy'}
)
