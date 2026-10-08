"""
SayoDevice backend. Complete but never run against real hardware.

Drop this and sayo_proto.py in macropad_gui/backends/ and add one line to
REGISTRY in backends/__init__.py:

    from .sayo import Sayo
    REGISTRY = (CH57x(), Sayo())

Until it is in REGISTRY the app cannot see it, so this file sitting here
changes nothing for anyone.

The protocol is in sayo_proto.py, decoded from WebHID captures of
sayodevice.com and checked against them line by line. Three things about
it shape the code here:

  * Reads and writes are the same command, 0x12. A four byte payload asks
    for a row of a table, a sixty byte payload is the row coming back or
    going in. Table 0x10 is the keys.
  * The pad says how many keys it has. Walk the index up and it answers
    with a no-such-index flag, so the key count is discovered rather than
    configured. It reports where each key physically is, too, so the grid
    is known rather than guessed.
  * Several bytes of a key's record drift on their own between reads, so
    a write is read-modify-write: read the record, change the two binding
    bytes, send it back. The vendor's own page does the same, which one
    capture caught it doing.

The pad echoes a write back about 100ms later, which is a real
acknowledgement. The CH57x says nothing, so this backend can confirm a
write where the other one can only hope.
"""

import errno

from . import sayo_proto as wire
from .base import Backend

REPORT_ID = wire.REPORT_ID
MAX_KEYS = 64             # a sanity stop in case a pad never says no


class Sayo(Backend):
    key = "sayo"
    name = "SayoDevice"
    vid = "8089"
    pids = ("000b",)      # the 2x4; other Sayo pids are untested
    layers = 1            # the firmware has more, we expose one for now
    max_keys = MAX_KEYS
    max_knobs = 0

    # ------------------------------------------------------------ protocol

    def action_byte(self, control):
        """Keys are their own index, counting from zero. No knobs."""
        if control.startswith("key"):
            return int(control[3:]) - 1
        raise ValueError(f"{self.name} has no knobs: {control}")

    def _request(self, table, index=0):
        return wire.report(wire.read_request(table, index))

    def _ask(self, device, table, index=0):
        """
        One row of one table, or None if the pad has no such row.

        Heartbeats arrive unasked about once a second and have to be
        stepped over, or the first one to land looks like the answer.
        """
        from .. import core
        for reply in core._exchange(device.path, self._request(table, index),
                                    want=4):
            if len(reply) < 2 or reply[0] != REPORT_ID:
                continue
            payload = reply[1:]
            if wire.is_heartbeat(payload):
                continue
            try:
                got = wire.parse_reply(payload)
            except ValueError:
                continue
            if got["table"] != table or got["index"] != index:
                continue
            return None if got["end"] else payload
        return None

    def _records(self, device, limit=MAX_KEYS):
        """Every key's record, in order, stopping where the pad says to."""
        out = []
        for i in range(limit):
            rec = self._ask(device, wire.TABLE_KEYS, i)
            if rec is None or not wire.is_key_record(rec):
                break
            out.append(rec)
        return out

    def _binding(self, record):
        """
        core.Binding for one key, or None if we cannot say what it does.

        None is the honest answer for a key type no capture covers, and
        it matters: three keys on one real pad are type 0x80, and reading
        those bytes as a modifier made them look like a bare "ctrl+shift"
        that nobody had set. The app shows None as unknown, which is true,
        and write() then refuses to overwrite it.
        """
        from .. import core
        kind, a, b = wire.read_binding(record)

        if kind == "consumer":
            return core.Binding(media=b) if b else None

        if kind != "keyboard":
            return None

        mods, code = a, b
        if not mods and not code:
            return core.Binding(none=True)
        names = [n for n, bit in core._MOD_ORDER if mods & bit]
        if code:
            name = core._KEYNAME_BY_CODE.get(code)
            if name is None:
                return None
            names.append(name)
        return core.Binding(keys="+".join(names))

    # --------------------------------------------------------------- read

    def info(self, device):
        """
        (keys, knobs) as the pad reports them, or None if it goes quiet.

        None matters: it means "did not answer", and the app then treats
        the pad as unsupported rather than writing to it.
        """
        records = self._records(device)
        return (len(records), 0) if records else None

    def model(self, device):
        """The name the pad calls itself, for the window title. May be ''."""
        reply = self._ask(device, wire.TABLE_NAME)
        return wire.device_name(reply) if reply else ""

    def read_layer(self, device, layer=1, layout=None):
        out = {}
        for i, rec in enumerate(self._records(device)):
            binding = self._binding(rec)
            if binding is not None:
                out[f"key{i + 1}"] = binding
        return out

    # -------------------------------------------------------------- write

    def write(self, device, control, binding, state, layer=1, _write=None):
        """
        Put one binding on the pad.

        Read the key's record first, because most of it is the pad's own
        and some of it moves between reads. If the read fails nothing has
        been sent, which is the one case where the app can promise the old
        binding is still there.
        """
        from .. import core
        import macropad as proto

        index = self.action_byte(control)

        try:
            record = self._ask(device, wire.TABLE_KEYS, index)
        except core.ReadError as e:
            raise core.WriteError(f"{control}: couldn't read the key first, so "
                                  f"nothing was changed ({e})",
                                  pad_touched=False, cause=e)
        if record is None or not wire.is_key_record(record):
            raise core.WriteError(f"{control}: the pad has no key {index + 1}",
                                  pad_touched=False)

        # Refuse to write over a key whose current type no capture covers.
        # Overwriting it would leave a key marked as one kind holding
        # another kind's bytes, and what the firmware does then is anyone's
        # guess. Better to say so and leave the pad alone.
        kind = wire.kind_of(record)
        if kind == "unknown":
            raise core.WriteError(
                f"{control}: this key is set to something this app hasn't "
                f"decoded yet (type 0x{record[wire.KIND_AT]:02x}), so it was "
                f"left alone. Clear it in the SayoDevice configurator first "
                f"and it becomes editable here.", pad_touched=False)

        payload = self._payload(record, binding)
        write = _write or proto.write_report
        try:
            write(device.path, wire.report(payload))
        except OSError as e:
            why = core._explain(e)
            untouched = e.errno in (errno.ENOENT, errno.ENODEV,
                                    errno.EACCES, errno.EPERM)
            if not untouched:
                state.mark_unknown(control, f"write interrupted: {why}", layer)
                state.save()
            raise core.WriteError(f"{control}: {why}",
                                  pad_touched=not untouched, cause=e)
        state.record(control, binding, layer)
        state.save()

    def _payload(self, record, binding):
        """The sealed write for this binding, on this key's own record."""
        from .. import core

        if binding.media:
            if binding.media not in wire.CONSUMER_BY_NAME:
                known = ", ".join(sorted(wire.CONSUMER_BY_NAME))
                raise core.WriteError(
                    f"{self.name}: {binding.media} isn't captured yet. This "
                    f"pad numbers media keys its own way, not by HID code, so "
                    f"each one needs seeing once. Known so far: {known}.",
                    pad_touched=False)
            return wire.patch_consumer(record, binding.media)
        return wire.patch_binding(record, *self._encode(binding))

    def _encode(self, binding):
        """
        (mods, usage) for one keyboard binding, or a WriteError saying why
        not.

        Parsing goes through macropad.MODIFIERS and macropad.KEYCODES, the
        same tables the CLI uses, so a binding typed once means the same
        thing on either family of pad. That is most of the point of having
        a backend seam at all.
        """
        from .. import core
        import macropad as proto

        if binding.none:
            return 0, 0
        if "," in binding.keys:
            raise core.WriteError(
                f"{self.name}: this pad holds one keystroke per key, not a "
                "sequence", pad_touched=False)
        mods, code = 0, 0
        for part in binding.keys.lower().split("+"):
            part = part.strip()
            if not part:
                continue
            if part in proto.MODIFIERS:
                mods |= proto.MODIFIERS[part]
            elif part in proto.KEYCODES:
                if code:
                    raise core.WriteError(
                        f"{self.name}: this pad holds one key plus modifiers, "
                        f"so {binding.keys!r} won't fit", pad_touched=False)
                code = proto.KEYCODES[part]
            else:
                raise core.WriteError(f"{self.name}: don't know the key "
                                      f"{part!r}", pad_touched=False)
        return mods, code

    # ------------------------------------------------------------- detect

    def detect(self, device):
        """
        Ask an unknown pad what it is, reading only.

        Two things have to line up before we call it a Sayo: a key table
        that answers in the right shape, and a model name. A pad sharing
        the vendor id but not the protocol fails one of them and is left
        alone.
        """
        from .. import core
        try:
            records = self._records(device)
        except core.ReadError as e:
            return core.Detection(why=f"it didn't answer: {e}")
        if not records:
            return core.Detection(why="it didn't answer the key table query")

        rows, cols = wire.grid_from_records(records)
        if rows * cols != len(records):
            rows, cols = 1, len(records)      # odd shape; one row is honest
        bindings = {}
        for i, rec in enumerate(records):
            got = self._binding(rec)
            if got is not None:
                bindings[f"key{i + 1}"] = got
        return core.Detection(speaks=True, keys=len(records), knobs=0,
                              layers=self.layers, bindings=bindings,
                              grid=(rows, cols), model=self.model(device))
