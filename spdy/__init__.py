# coding: utf-8
import sys
if sys.version_info[0] >= 3:
    from spdy.context import *
else:
    from spdy.context_v2 import *