"""
The CH57x family: 1189:8840 and its relatives.

Reverse engineered from USB captures of the vendor's own software, and every
packet in tests/captures is replayed by the test suite. The wire format lives
in macropad.py and is not to be edited without a capture to back it up.

Two things about this firmware shape the code:

  * It keeps 15 key slots and 3 knob slots whatever hardware is soldered on,
    so a layer read always answers 24 slots. Only the 0xFB query says how
    many of those are real.
  * There is no addressing by name. A control is a slot number: keys are
    1 to 15, knobs start at 0x10 and take three apiece.
"""

import errno
import time

import macropad as proto

from .base import Backend

WRITE_GAP = 0.02          # the same pause the CLI leaves between reports
DIAL_ACTIONS = ("left", "push", "right")


class CH57x(Backend):
    key = "ch57x"
    name = "CH57x macro pad"
    vid = "1189"
    pids = ("8840",)      # confirmed; siblings share the vendor id, not the
                          # protocol, so they go through detect() first
    layers = proto.LAYERS
    max_keys = proto.KEY_SLOTS
    max_knobs = proto.KNOB_SLOTS

    # ------------------------------------------------------------ protocol

    def action_byte(self, control):
        """
        Keys count from 1; knobs start at 0x10, three apiece. Confirmed on
        1189:8840 both by writing and by reading back, and it matches the
        slots the pad reports for itself.
        """
        control = control.lower()
        if control.startswith("key"):
            return int(control[3:])
        dial, act = control.split("-")
        return proto.KNOB_BASE + (int(dial[4:]) - 1) * 3 + DIAL_ACTIONS.index(act)

    # -------------------------------------------------------------- decode

    def decode_info(self, report):
        """(keys, knobs) from a 0xFB reply, or None."""
        if len(report) < 4 or report[1] != proto.MAGIC_INFO:
            return None
        return report[2], report[3]

    def decode_config(self, report, layout=None):
        """
        (control, layer, Binding) from a config report, or None.

        layout decides which slots count as real controls, and it matters
        more than it looks: decode a 15 key pad against a 12 key layout and
        keys 13 to 15 and the third knob vanish without a word.
        """
        from .. import core
        if len(report) < 13 or report[1] not in (proto.MAGIC_NATIVE,
                                                 proto.MAGIC_READ):
            return None
        action, layer, kind = report[2], report[3], report[4]
        controls = (layout or core.DEFAULT_LAYOUT).control_for_action
        control = controls.get(action)
        if control is None:
            return None
        delay = report[5] | (report[6] << 8)
        count = report[10]

        if kind == proto.KeyType.MULTIMEDIA and count:
            media = core._MEDIA_BY_USAGE.get(report[11] | (report[12] << 8))
            return (control, layer, core.Binding(media=media)) if media else None

        if count == 0 and kind in (proto.KeyType.NONE, proto.KeyType.BASIC):
            mods, code = report[11], report[12]
            if not mods and not code:
                return control, layer, core.Binding(none=True)
            return None

        if kind in (proto.KeyType.NONE, proto.KeyType.BASIC) and count:
            steps = []
            for i in range(count):
                off = 11 + 2 * i
                if off + 1 >= len(report):
                    return None
                mods, code = report[off], report[off + 1]
                names = [n for n, bit in core._MOD_ORDER if mods & bit]
                if code:
                    if code not in core._KEYNAME_BY_CODE:
                        return None
                    names.append(core._KEYNAME_BY_CODE[code])
                steps.append("+".join(names))
            return control, layer, core.Binding(keys=",".join(steps), delay=delay)
        return None

    # ---------------------------------------------------------------- read

    def info(self, device):
        from .. import core
        for reply in core._exchange(device.path,
                                    proto.native_info(device.report_id), want=1):
            got = self.decode_info(reply)
            if got:
                return got
        return None

    def read_layer(self, device, layer=1, layout=None):
        from .. import core
        out = {}
        request = proto.native_read(device.report_id, layer)
        for reply in core._exchange(device.path, request):
            decoded = self.decode_config(reply, layout)
            if not decoded:
                continue
            control, got_layer, binding = decoded
            if got_layer == layer:
                out[control] = binding
        return out

    # --------------------------------------------------------------- write

    def write(self, device, control, binding, state, layer=1, _write=None):
        """
        Send one binding (config report, then commit) and update the shadow
        state. On success the state file is already saved.
        """
        from .. import core
        write = _write or proto.write_report
        reports = binding.reports(device.report_id, self.action_byte(control),
                                  layer)
        sent = 0
        try:
            for r in reports:
                write(device.path, r)
                sent += 1
                time.sleep(WRITE_GAP)
        except OSError as e:
            why = core._explain(e)
            # if the very first write failed on open, nothing reached the pad
            untouched = sent == 0 and e.errno in (errno.ENOENT, errno.ENODEV,
                                                  errno.EACCES, errno.EPERM)
            if not untouched:
                state.mark_unknown(control, f"write interrupted after {sent} of "
                                   f"{len(reports)} reports: {why}", layer)
                state.save()
            raise core.WriteError(f"{control}: {why}",
                                  pad_touched=not untouched, cause=e)
        state.record(control, binding, layer)
        state.save()

    # -------------------------------------------------------------- detect

    def detect(self, device):
        """
        Ask an unknown pad what it is, without configuring anything.

        Both commands are queries. We only conclude the pad speaks this
        protocol if it answers both in the right shape: a well formed info
        reply, and a layer whose controls are exactly the slots that reply
        implies. A pad from another family fails one of those and we leave
        it alone.
        """
        from .. import core
        try:
            info = self.info(device)
        except core.ReadError as e:
            return core.Detection(why=f"it didn't answer: {e}")
        if not info:
            return core.Detection(why="it didn't answer the 'what are you' query")

        keys, knobs = info
        if not self.supports(keys, knobs):
            return core.Detection(why=f"it reported {keys} keys and {knobs} "
                                      "knobs, which isn't a pad this protocol "
                                      "can describe")

        probe = core.Layout(keys, knobs, rows=keys, cols=1)   # geometry unused
        expected = set(probe.control_for_action)
        try:
            replies = core._exchange(device.path,
                                     proto.native_read(device.report_id, 1))
        except core.ReadError as e:
            return core.Detection(
                why=f"it answered the first query but not the second: {e}")

        seen, bindings = set(), {}
        for reply in replies:
            if len(reply) < 13 or reply[1] != proto.MAGIC_READ:
                continue
            action, layer = reply[2], reply[3]
            seen.add(action)
            if action not in expected or layer != 1:
                continue
            decoded = self.decode_config(reply, probe)
            if decoded:
                bindings[probe.control_for_action[action]] = decoded[2]

        missing = expected - seen
        if missing:
            return core.Detection(
                why=f"it described {keys} keys and {knobs} knobs but didn't "
                    f"report {len(missing)} of them, so this isn't the "
                    "protocol it speaks")

        return core.Detection(speaks=True, keys=keys, knobs=knobs,
                              layers=self.layers, bindings=bindings)
