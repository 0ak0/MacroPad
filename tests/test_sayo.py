"""
The SayoDevice backend, replayed against real captures.

No Sayo pad has ever been written to, so these tests stand in for the
hardware: a fake pad answers out of two WebHID captures of the vendor's
own configurator, and the backend has to come out with the same answers
the configurator did. The write test is the important one. It asserts
that our packet is byte for byte the packet the vendor's page sent for
the same change, which is the only check available until somebody runs
it on a desk.

The backend is deliberately not in backends.REGISTRY, so none of this
affects a real pad. Adding it there is one line, once a write has been
confirmed on hardware.
"""

import unittest
from unittest import mock

from macropad_gui import core
from macropad_gui.backends import sayo_proto as wire
from macropad_gui.backends.sayo import Sayo


def _payloads(direction):
    return [bytes.fromhex(h) for d, h in wire.STARTUP if d == direction]


class FakePad:
    """
    Answers read requests out of the capture and remembers writes.

    It replies the way the real pad does: the report id on the front, a
    heartbeat first so the backend has to step over one, and nothing at
    all for an index that does not exist.
    """

    def __init__(self, keys=8, name=True):
        self.path = "/dev/hidraw-fake"
        self.vid, self.pid, self.report_id = "8089", "000b", wire.REPORT_ID
        self.name = "SayoDevice"
        self.keys = keys
        self.offer_name = name
        self.written = []
        self.records = {i: r for i, r in enumerate(wire.LIVE)}

    # the heartbeat the real pad sends unasked, roughly once a second
    HEARTBEAT = bytes([wire.REPORT_ID]) + bytes(63)

    def exchange(self, path, request, want=None):
        assert path == self.path
        assert len(request) == 64 and request[0] == wire.REPORT_ID
        asked = wire.parse_reply(request[1:])
        table, index = asked["table"], asked["index"]
        out = [self.HEARTBEAT]

        if table == wire.TABLE_KEYS:
            if index < self.keys:
                out.append(bytes([wire.REPORT_ID]) + self.records[index])
            else:
                end = bytearray(wire.read_request(table, index))
                end[wire.FLAG_AT] = wire.NO_SUCH_INDEX
                out.append(bytes([wire.REPORT_ID]) + wire.seal(end))
        elif table == wire.TABLE_NAME and self.offer_name:
            out.append(bytes([wire.REPORT_ID]) + _payloads("in")[1])
        return out

    def write_report(self, path, report):
        assert path == self.path
        self.written.append(bytes(report))


class Capture(unittest.TestCase):
    """The captures themselves, before any backend touches them."""

    def test_every_captured_packet_verifies(self):
        for direction, h in wire.STARTUP:
            payload = bytes.fromhex(h)
            self.assertEqual(len(payload), 63, h[:8])
            self.assertTrue(wire.verify(payload), f"{h[:8]} checksum")

    def test_the_pad_reported_eight_keys_in_a_four_by_two_grid(self):
        self.assertEqual(len(wire.LIVE), 8)
        self.assertEqual(wire.grid_from_records(wire.LIVE), (2, 4))

    def test_read_requests_match_the_vendors_own(self):
        asked_for = 0
        for want in _payloads("out"):
            if want[wire.LEN_AT] != wire.REQUEST_LEN:
                continue                       # that one is a write
            asked = wire.parse_reply(want)
            mine = wire.read_request(asked["table"], asked["index"])
            self.assertEqual(mine, want, f"table {asked['table']:#04x}")
            asked_for += 1
        self.assertGreater(asked_for, 2, "the capture should hold several reads")


class Reading(unittest.TestCase):

    def setUp(self):
        self.pad = FakePad()
        self.backend = Sayo()
        patch = mock.patch.object(core, "_exchange", self.pad.exchange)
        patch.start()
        self.addCleanup(patch.stop)

    def test_it_discovers_the_key_count_rather_than_assuming_one(self):
        self.assertEqual(self.backend.info(self.pad), (8, 0))

    def test_a_smaller_pad_reports_itself_smaller(self):
        self.pad.keys = 4
        self.assertEqual(self.backend.info(self.pad), (4, 0))

    def test_a_silent_pad_gives_none_not_a_fake_shape(self):
        """None is what makes the app refuse to write. It has to stay None."""
        self.pad.keys = 0
        self.assertIsNone(self.backend.info(self.pad))

    def test_heartbeats_do_not_get_mistaken_for_answers(self):
        self.pad.HEARTBEAT = bytes([wire.REPORT_ID]) + bytes(63)
        self.assertEqual(self.backend.info(self.pad), (8, 0))

    def test_bindings_read_back_as_the_configurator_shows_them(self):
        got = self.backend.read_layer(self.pad)
        self.assertEqual(got["key1"].keys, "ctrl+numpadplus")
        self.assertEqual(got["key5"].keys, "ctrl+numpadminus")
        self.assertEqual(got["key7"].keys, "ctrl+shift+alt+rightbracket")
        self.assertTrue(got["key8"].none)

    def test_an_uncaptured_key_type_is_left_out_rather_than_guessed(self):
        """
        Keys 2, 3 and 4 of the captured pad are type 0x80, which the owner
        says are media transport keys. Read as a modifier they came out as
        a bare "ctrl+shift" and "alt" that nobody had set, which is worse
        than admitting we do not know.
        """
        got = self.backend.read_layer(self.pad)
        for control in ("key2", "key3", "key4"):
            self.assertNotIn(control, got, control)
        for control in ("key1", "key5", "key6", "key7", "key8"):
            self.assertIn(control, got, control)

    def test_it_reads_its_own_model_name(self):
        self.assertEqual(self.backend.model(self.pad), "SayoDevice 2x4V RGB")


class Detecting(unittest.TestCase):

    def setUp(self):
        self.pad = FakePad()
        self.backend = Sayo()
        patch = mock.patch.object(core, "_exchange", self.pad.exchange)
        patch.start()
        self.addCleanup(patch.stop)

    def test_it_uses_the_pads_geometry_instead_of_guessing(self):
        found = self.backend.detect(self.pad)
        self.assertTrue(found.speaks)
        self.assertEqual((found.keys, found.knobs), (8, 0))
        self.assertEqual(found.grid, (2, 4))
        self.assertEqual(found.layout.rows, 2)
        self.assertEqual(found.layout.cols, 4)
        self.assertEqual(found.layout.name, "SayoDevice 2x4V RGB")

    def test_a_pad_that_says_nothing_is_left_alone(self):
        self.pad.keys = 0
        found = self.backend.detect(self.pad)
        self.assertFalse(found.speaks)
        self.assertIn("key table", found.why)


class Writing(unittest.TestCase):

    def setUp(self):
        self.pad = FakePad()
        self.backend = Sayo()
        self.state = mock.Mock()
        patch = mock.patch.object(core, "_exchange", self.pad.exchange)
        patch.start()
        self.addCleanup(patch.stop)

    def _write(self, control, binding):
        self.backend.write(self.pad, control, binding, self.state,
                           _write=self.pad.write_report)

    def test_our_packet_is_the_one_the_vendors_page_sent(self):
        """
        The capture caught the configurator reading key 8 and then setting
        it to p. Same starting record, same change, so the bytes have to
        match, checksum included.
        """
        theirs = _payloads("out")[-1]
        self._write("key8", core.Binding(keys="p"))
        self.assertEqual(len(self.pad.written), 1)
        self.assertEqual(self.pad.written[0], wire.report(theirs))

    def test_it_keeps_the_pads_own_bytes_and_changes_only_the_binding(self):
        before = wire.LIVE[0]
        self._write("key1", core.Binding(keys="ctrl+shift+a"))
        after = self.pad.written[0][1:]
        moved = [i for i in range(63) if after[i] != before[i]]
        self.assertEqual(moved, [wire.CHECK_AT, wire.CHECK_AT + 1,
                                 wire.MOD_AT, wire.KEYCODE_AT])
        self.assertEqual(after[wire.MOD_AT], 0x03)
        self.assertEqual(after[wire.KEYCODE_AT], 0x04)

    def test_clearing_a_key_zeroes_both_binding_bytes(self):
        self._write("key1", core.Binding(none=True))
        after = self.pad.written[0][1:]
        self.assertEqual((after[wire.MOD_AT], after[wire.KEYCODE_AT]), (0, 0))

    def test_a_key_the_pad_does_not_have_is_refused_before_sending(self):
        with self.assertRaises(core.WriteError) as caught:
            self._write("key9", core.Binding(keys="a"))
        self.assertFalse(caught.exception.pad_touched)
        self.assertEqual(self.pad.written, [])

    def test_the_four_captured_media_keys_write(self):
        """
        Each one has to come out as the exact packet the vendor's page sent
        for the same change, which is what the third capture recorded.
        """
        for name, want in wire.CONSUMER_CAPTURE.items():
            self.pad.written.clear()
            self._write("key8", core.Binding(media=name))
            self.assertEqual(self.pad.written[0], wire.report(bytes.fromhex(want)),
                             name)

    def test_a_media_key_we_have_not_captured_is_refused(self):
        """
        This pad numbers media keys its own way, not by HID code, so a name
        we have never seen set cannot be derived. Saying so beats writing a
        number we made up.
        """
        with self.assertRaises(core.WriteError) as caught:
            self._write("key8", core.Binding(media="playpause"))
        self.assertIn("captured", str(caught.exception).lower())
        self.assertFalse(caught.exception.pad_touched)
        self.assertEqual(self.pad.written, [])

    def test_an_uncaptured_key_type_is_never_overwritten(self):
        """
        The real risk this guards: writing a shortcut onto a type 0x80 key
        would leave it flagged as one kind of key holding another kind's
        bytes. Nothing reaches the pad, so the old binding survives.
        """
        with self.assertRaises(core.WriteError) as caught:
            self._write("key2", core.Binding(keys="a"))
        self.assertFalse(caught.exception.pad_touched)
        self.assertEqual(self.pad.written, [])
        self.assertIn("0x80", str(caught.exception))

    def test_switching_a_media_key_to_a_shortcut_clears_the_type(self):
        self.pad.records[7] = bytes.fromhex(wire.CONSUMER_CAPTURE["volumeup"])
        self._write("key8", core.Binding(keys="ctrl+c"))
        after = self.pad.written[0][1:]
        self.assertEqual(after[wire.KIND_AT], wire.KIND_KEYBOARD)
        self.assertEqual(wire.read_binding(after), ("keyboard", 0x01, 0x06))

    def test_a_keyboard_write_keeps_the_low_bit_of_the_type(self):
        """
        Key 8 was type 0x01 and the vendor's page set it to p without
        touching that bit, so neither do we.
        """
        self._write("key8", core.Binding(keys="p"))
        self.assertEqual(self.pad.written[0][1:][wire.KIND_AT], 0x01)

    def test_a_sequence_is_refused_because_the_pad_holds_one_keystroke(self):
        with self.assertRaises(core.WriteError) as caught:
            self._write("key1", core.Binding(keys="a,b,c"))
        self.assertFalse(caught.exception.pad_touched)

    def test_knobs_are_refused_since_this_pad_has_none(self):
        with self.assertRaises(ValueError):
            self.backend.action_byte("dial1left")

    def test_everything_written_reseals_and_round_trips(self):
        for combo in ("a", "ctrl+c", "ctrl+shift+t", "meta+l", "super+l",
                      "win+l", "f5", "space", "numpadminus"):
            self.pad.written.clear()
            self._write("key1", core.Binding(keys=combo))
            payload = self.pad.written[0][1:]
            self.assertTrue(wire.verify(payload), combo)
            mods, code = wire.parse_combo(combo)
            self.assertEqual(payload[wire.MOD_AT], mods, combo)
            self.assertEqual(payload[wire.KEYCODE_AT], code, combo)


class Drawing(unittest.TestCase):
    """
    Every pad before this one had knobs, so a knobless board is a shape the
    drawing code has never been given. It must come out in every theme
    rather than dividing by a knob count of zero somewhere.
    """

    def test_a_knobless_pad_draws_in_every_theme(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QPixmap
        from macropad_gui import padview, themes

        QApplication.instance() or QApplication([])
        shape = core.Layout(8, 0, 2, 4, "SayoDevice 2x4V RGB")
        for name, theme in sorted(themes.THEMES.items()):
            padview.apply_theme(theme)
            view = padview.PadView()
            view.layout = shape
            view.looks = {c: padview.Look() for c in shape.control_ids}
            view.resize(900, 520)
            shot = QPixmap(view.size())
            view.render(shot)
            self.assertFalse(shot.isNull(), name)

    def test_a_knobless_layout_has_only_keys(self):
        shape = core.Layout(8, 0, 2, 4)
        self.assertEqual(len(shape.control_ids), 8)
        self.assertFalse([c for c in shape.control_ids if c.startswith("dial")])


class Routing(unittest.TestCase):
    """
    The two families must not reach into each other. A Sayo pad has to go
    to the Sayo backend and a CH57x to the CH57x one, and a Sayo pid we
    have never seen must not be claimed outright: it goes through detect()
    first, the same as an unknown CH57x sibling.
    """

    def test_a_sayo_pad_routes_to_the_sayo_backend(self):
        from macropad_gui import backends
        self.assertEqual(backends.for_vid_pid("8089", "000b").key, "sayo")

    def test_a_ch57x_pad_still_routes_to_ch57x(self):
        from macropad_gui import backends
        self.assertEqual(backends.for_vid_pid("1189", "8840").key, "ch57x")

    def test_the_ch57x_backend_does_not_claim_a_sayo(self):
        from macropad_gui import backends
        self.assertFalse(backends.DEFAULT.claims("8089", "000b"))

    def test_an_unseen_sayo_pid_is_not_claimed_outright(self):
        from macropad_gui import backends
        self.assertIsNone(backends.for_vid_pid("8089", "0099"))
        self.assertTrue(Sayo().could_claim("8089", "0099"))

    def test_the_installer_offers_a_rule_for_the_sayo_vendor(self):
        from macropad_gui import core
        self.assertTrue(any("8089" in line for line in core.rule_lines()))


if __name__ == "__main__":
    unittest.main()
