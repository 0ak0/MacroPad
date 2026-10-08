"""
What a device family has to provide.

These raise rather than returning something vague, so a half written backend
fails at the call it can't answer instead of writing wrong bytes to somebody's
hardware.
"""


class Backend:
    key = ""              # short id, used in settings and messages
    name = ""             # what a person would call this family
    vid = ""              # USB vendor id, lowercase hex, no 0x
    pids = ()             # product ids this backend is CONFIRMED on
    layers = 1
    max_keys = 0
    max_knobs = 0

    def claims(self, vid, pid):
        """True only for ids this backend has been confirmed on."""
        if vid.lower() != self.vid.lower():
            return False
        return not self.pids or pid.lower() in {p.lower() for p in self.pids}

    def could_claim(self, vid, pid):
        # Siblings share a vendor id but not always a protocol. The scan and
        # the udev rule cover the whole vendor so an unconfirmed sibling is
        # still found and offered detection; claims() stays strict so it is
        # never written to on the strength of its vendor id alone.
        return vid.lower() == self.vid.lower()

    def udev_rule(self):
        return (f'KERNEL=="hidraw*", ATTRS{{idVendor}}=="{self.vid}", '
                f'TAG+="uaccess"')

    def adopt(self, layout):
        """Where a family can say more about a shape than detection found."""
        return layout

    def supports(self, keys, knobs):
        return 1 <= keys <= self.max_keys and 0 <= knobs <= self.max_knobs

    # The six a family must answer.

    def action_byte(self, control):
        """The slot number this family uses for a control id."""
        raise NotImplementedError

    def info(self, device):
        """(keys, knobs) as the pad reports them, or None."""
        raise NotImplementedError

    def read_layer(self, device, layer=1, layout=None):
        raise NotImplementedError

    def write(self, device, control, binding, state, layer=1, _write=None):
        raise NotImplementedError

    def detect(self, device):
        """Read only. Must say no rather than guess."""
        raise NotImplementedError

    def __repr__(self):
        return f"<{type(self).__name__} {self.vid}:{'/'.join(self.pids) or '*'}>"
