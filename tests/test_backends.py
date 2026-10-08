"""
The backend seam.

A split you cannot exercise is not a split, so these tests register a second,
imaginary family and check that the app routes to it: different vendor id,
different slot numbering, different everything. Nothing here touches real
hardware and the fake backend is removed again afterwards.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from macropad_gui import backends, core
from macropad_gui.backends.base import Backend
import macropad as proto


class Imaginary(Backend):
    """
    Stands in for a second device family. Eight keys, no knobs, slots
    numbered from 0x20 so nothing it returns could be mistaken for a CH57x
    answer that leaked through.
    """
    key = "imaginary"
    name = "Imaginary pad"
    vid = "c0de"
    pids = ("0001",)
    layers = 1
    max_keys = 8
    max_knobs = 0

    def __init__(self):
        self.calls = []

    def action_byte(self, control):
        self.calls.append(("action_byte", control))
        return 0x20 + int(control[3:]) - 1

    def info(self, device):
        self.calls.append(("info", device.path))
        return 8, 0

    def read_layer(self, device, layer=1, layout=None):
        self.calls.append(("read_layer", layer))
        return {f"key{i}": core.Binding(keys="a") for i in range(1, 9)}

    def write(self, device, control, binding, state, layer=1, _write=None):
        self.calls.append(("write", control))
        state.record(control, binding, layer)
        state.save()

    def detect(self, device):
        self.calls.append(("detect", device.path))
        return core.Detection(speaks=True, keys=8, knobs=0, layers=1,
                              bindings={"key1": core.Binding(keys="a")})


def fake_device(vid="c0de", pid="0001", path="/dev/null-pad"):
    return core.Device(path=path, report_id=3, writable=True, vid=vid, pid=pid)


class Registry(unittest.TestCase):

    def setUp(self):
        self.fake = Imaginary()
        self._saved = backends.REGISTRY
        backends.REGISTRY = backends.REGISTRY + (self.fake,)

    def tearDown(self):
        backends.REGISTRY = self._saved

    def test_each_family_gets_its_own_device(self):
        self.assertIs(backends.for_vid_pid("c0de", "0001"), self.fake)
        self.assertIsInstance(backends.for_vid_pid("1189", "8840"),
                              backends.CH57x)

    def test_an_unknown_id_is_claimed_by_nobody(self):
        self.assertIsNone(backends.for_vid_pid("dead", "beef"))

    def test_a_sibling_under_a_known_vendor_is_not_claimed(self):
        """
        1189:8890 exists and is not ours. It must not be claimed on the
        strength of its vendor id, or the app would write to a pad whose
        protocol it has never confirmed.
        """
        self.assertIsNone(backends.for_vid_pid("1189", "8890"))
        ch = backends.CH57x()
        self.assertTrue(ch.could_claim("1189", "8890"))   # still worth finding

    def test_for_device_falls_back_rather_than_returning_none(self):
        self.assertIsInstance(backends.for_device(None), backends.CH57x)
        self.assertIsInstance(backends.for_device(fake_device("1189", "8890")),
                              backends.CH57x)


class Routing(unittest.TestCase):
    """core's functions must land on the backend that owns the device."""

    def setUp(self):
        self.fake = Imaginary()
        self._saved = backends.REGISTRY
        backends.REGISTRY = backends.REGISTRY + (self.fake,)
        self.dir = tempfile.TemporaryDirectory()
        self.state = core.State(Path(self.dir.name) / "s.json")

    def tearDown(self):
        backends.REGISTRY = self._saved
        self.dir.cleanup()

    def test_detect_routes(self):
        found = core.detect(fake_device())
        self.assertTrue(found.speaks)
        self.assertEqual((found.keys, found.knobs), (8, 0))
        self.assertIn(("detect", "/dev/null-pad"), self.fake.calls)

    def test_read_routes(self):
        got = core.read_layer(fake_device())
        self.assertEqual(len(got), 8)
        self.assertIn(("read_layer", 1), self.fake.calls)

    def test_info_routes(self):
        self.assertEqual(core.read_info(fake_device()), (8, 0))

    def test_write_routes(self):
        core.write_binding(fake_device(), "key1", core.Binding(keys="a"),
                           self.state)
        self.assertIn(("write", "key1"), self.fake.calls)
        self.assertEqual(self.state.get("key1").binding, core.Binding(keys="a"))

    def test_slot_numbering_is_per_family(self):
        self.assertEqual(self.fake.action_byte("key1"), 0x20)
        self.assertEqual(core.action_byte("key1"), 1)          # still CH57x
        self.assertEqual(core.action_byte("key1", self.fake), 0x20)

    def test_the_real_backend_is_untouched_by_the_fake(self):
        ch = backends.for_vid_pid("1189", "8840")
        self.assertEqual(ch.action_byte("dial2-right"), 0x15)
        self.assertEqual(ch.max_keys, proto.KEY_SLOTS)

    def test_discovery_covers_every_vendor(self):
        self.assertEqual(core.vendors(), {"1189", "8089", "c0de"})
        with mock.patch.object(proto, "find_devices", return_value=[]) as f:
            core.discover()
        f.assert_called_once()
        self.assertEqual(f.call_args[0][0], {"1189", "8089", "c0de"})

    def test_one_udev_rule_per_vendor(self):
        lines = core.rule_lines()
        self.assertEqual(len(lines), len(backends.REGISTRY))
        self.assertTrue(any('"1189"' in l for l in lines))
        self.assertTrue(any('"c0de"' in l for l in lines))
        for line in lines:
            self.assertIn('TAG+="uaccess"', line)
            self.assertIn('KERNEL=="hidraw*"', line)


class HalfWritten(unittest.TestCase):
    """A backend that forgets a method should fail loudly, not silently."""

    def test_the_base_class_refuses_to_guess(self):
        bare = Backend()
        dev = fake_device()
        for call in (lambda: bare.action_byte("key1"),
                     lambda: bare.info(dev),
                     lambda: bare.read_layer(dev),
                     lambda: bare.write(dev, "key1", None, None),
                     lambda: bare.detect(dev)):
            with self.assertRaises(NotImplementedError):
                call()


class StateFiles(unittest.TestCase):

    def test_the_default_file_name_has_not_changed(self):
        """Renaming it would orphan every existing user's bindings."""
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(core, "config_dir", return_value=Path(d)):
                self.assertEqual(core.State().path.name, "state-1189-8840.json")

    def test_a_second_family_gets_its_own_file(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(core, "config_dir", return_value=Path(d)):
                s = core.State(device_id="c0de:0001")
                self.assertEqual(s.path.name, "state-c0de-0001.json")
                s.record("key1", core.Binding(keys="a"))
                s.save()
                import json
                self.assertEqual(json.loads(s.path.read_text())["device"],
                                 "c0de:0001")


if __name__ == "__main__":
    unittest.main()
