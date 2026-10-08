"""
One device family per backend.

Everything above this line works in terms of a Layout and a set of control
ids and doesn't care what the hardware speaks. Everything below it is one
pad family's protocol. Adding a family means writing the six methods in
base.py and listing the class here.
"""

from .ch57x import CH57x
from .sayo import Sayo

REGISTRY = (CH57x(), Sayo())   # tried in order; first to claim a device wins
DEFAULT = REGISTRY[0]


def for_vid_pid(vid, pid):
    for backend in REGISTRY:
        if backend.claims(str(vid).lower(), str(pid).lower()):
            return backend
    return None


def for_device(device):
    # Falls back rather than returning None, so callers that only ever see
    # one family stay simple. Use for_vid_pid when "nobody owns this" is an
    # answer you need to act on.
    if device is None:
        return DEFAULT
    return for_vid_pid(device.vid, device.pid) or DEFAULT


def known_ids():
    return [(b.vid, b.pids, b.name) for b in REGISTRY]
