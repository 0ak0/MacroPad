"""
SayoDevice 8089:000b wire format.

Worked out from WebHID captures of sayodevice.com. Everything here is
checked against those captures by the self test at the bottom: run this
file directly and it rebuilds every captured packet byte for byte.

    python3 sayo_proto.py

A report is 64 bytes: report id 0x21, then 63 bytes of payload. One
command byte, 0x12, covers both directions. A four byte payload is a
question, a sixty byte payload is an answer or a write.

    payload
      0      0x12   the only command we have seen
      1-2    checksum, little endian (see checksum())
      3      how many bytes from byte 4 on carry meaning. 0x04 for a
             read request, 0x3c for a key record
      4      flags. 0x00 asking, 0x40 in a reply means no such index
      5      which table (see TABLES)
      6      index within that table
      7+     the data

Table 0x10 is the keys, one record per key, and a record looks like this:

      7      0x01
      8-10   0x00
      11-18  x, y, width, height on the pad face, four little endian 16
             bit numbers. Key 1 of an 8 key pad is at 1250,1250 and is
             1800 square, giving a 4 by 2 grid with a pitch of 1900
      19     0x64   100
      23     what kind of key this is (see KINDS). It decides what bytes
             27 and 28 mean, and the configurator writes it
      27-28  the binding, read according to byte 23
      44     a counter of some sort, drifts on its own
      51-52  also drifts on its own, probably a press count or timestamp

Byte 23 took two captures to pin down. A capture of the page setting
volume and brightness keys shows it going from 0x01 to 0x03 and byte 27
carrying a small code, while an earlier capture of the page setting a
plain letter left it alone. So it is the key's type, not drifting state:

      0x00, 0x01   a keyboard shortcut. 27 is the modifier bitmask,
                   standard HID, and 28 is the usage code. The low bit
                   appears either way and is something else, so it is
                   preserved rather than understood
      0x03         volume and brightness. 27 is a code of Sayo's own
                   (see CONSUMER), 28 is zero
      anything     a kind we have not captured. On one real pad, 0x80
      else         is three media transport keys. Read as unknown and
                   never written over

Writing is read-modify-write: read the key's record, set bytes 23, 27
and 28, reseal. The vendor's own page does exactly that, which one
capture caught in the act. Nothing else in the record is ours to touch,
because bytes 44 and 51-52 really do move on their own.
"""

from pathlib import Path

REPORT_ID = 0x21
CMD = 0x12            # both directions, both reads and writes
KEY_AT = 6
KIND_AT = 23          # what sort of key it is, which decides 27 and 28
MOD_AT = 27
KEYCODE_AT = 28
CHECK_AT = 1          # payload bytes 1 and 2, little endian
LEN_AT = 3
FLAG_AT = 4
TABLE_AT = 5
DATA_AT = 7

RECORD_LEN = 0x3C     # byte 3 of a key record
REQUEST_LEN = 0x04    # byte 3 of a read request
NO_SUCH_INDEX = 0x40  # byte 4 of a reply, meaning you ran off the end

# Byte 5. The pad lists the ones it has in table 0x00; these are the ones
# we have a use for.
TABLE_DIRECTORY = 0x00
TABLE_NAME = 0x01     # the model name, UTF-16LE
TABLE_INFO = 0x02     # vid and pid at bytes 19 to 22, and uptime
TABLE_KEYS = 0x10     # one record per key, the ones we care about

# Table 0x01 and 0x19 want 0x0c in the flag byte rather than 0x00. Why is
# not clear, but the page is consistent about it and so are we.
FLAGS = {TABLE_NAME: 0x0C}

CMD_WRITE_KEY = CMD   # old name, kept so nothing outside here breaks

# Byte 23. KEYBOARD_KINDS are the two values seen alongside a real
# keyboard shortcut; the low bit is some other flag we carry along.
KIND_KEYBOARD = 0x00
KIND_CONSUMER = 0x03
KEYBOARD_KINDS = (0x00, 0x01)
KINDS = {KIND_KEYBOARD: "keyboard", 0x01: "keyboard", KIND_CONSUMER: "consumer"}

# Byte 27 when byte 23 is 0x03. Sayo's own numbering, not HID consumer
# codes, so every one of these comes from a capture and no others are
# guessed. The names match macropad.MEDIA_KEYS so a media binding means
# the same thing on either family of pad.
CONSUMER = {
    0x01: "brightnessup",
    0x02: "brightnessdown",
    0x0A: "volumeup",
    0x0B: "volumedown",
}
CONSUMER_BY_NAME = {v: k for k, v in CONSUMER.items()}

# Captured records, each the exact 63 bytes sayodevice.com sent, taken from
# CAPTURED below so the two can never drift apart. Byte 6 is the key index,
# so these cover keys 1, 2 and 8 of an 8 key pad.
CAPTURED = [
    "1256683c00100701000000261b4e0c080708076400000000000000000400000000000000000000000000000015000000000000000000000000000000000000",
    "1256693c00100701000000261b4e0c080708076400000000000000000500000000000000000000000000000015000000000000000000000000000000000000",
    "1256773c00100701000000261b4e0c080708076400000000000000001300000000000000000000000000000015000000000000000000000000000000000000",
    "1258643c00100701000000261b4e0c080708076400000000000000020000000000000000000000000000000015000000000000000000000000000000000000",
    "125e643c00100701000000261b4e0c080708076400000000000000080000000000000000000000000000000015000000000000000000000000000000000000",
    "1256643c00100701000000261b4e0c080708076400000000000000000000000000000000000000000000000015000000000000000000000000000000000000",
    "12c17e3c00100001000000e204e20408070807640000000000000000040000030000000e000000000000000000000000000000000000000100000009500000",
    "122a863c001001010000004e0ce20408070807640000000000000000040000030000000c0000000000000000000000000000000000000000000000094f0000",
]

# A second capture, of the page starting up, which is where the read
# command came from. Request then reply, in the order they happened.
STARTUP = [
    # the directory: which tables this pad has
    ("out", "122512040000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"),
    ("in", "1250e11f00000007007b000000004b000004040102030d0e101112161718191a1e1f0000000000000000000000000000000000000000000000000000000000"),
    # the model name
    ("out", "12261e040c01000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"),
    ("in", "129124340c01005300610079006f00440065007600690063006500200032007800340056002000520047004200000000000000000000000000000000000000"),
    # the eight keys, asked for one at a time
    ("out", "123512040010000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"),
    ("in", "12c2d13c00100001000000e204e20408070807640000000000000001570000030000000e000000000000000000000000000000000000000100000009500000"),
    ("in", "12ad823c001001010000004e0ce20408070807640000008000000003000000030000000c0000000000000000000000000000000000000000000000094f0000"),
    ("in", "1296863c00100201000000ba13e20408070807640000008000000004000000030000000f000000810000000000000000000000014a00000000000000000000"),
    ("in", "126f8f3c00100301000000261be204080708076400000080000000010000000000000000000000000000000000000000000000044b00000000000000000000"),
    ("in", "1214a93c00100401000000e2044e0c08070807640000000000000001560000010000000000000000000000001d000000000000000000000000000000000000"),
    ("in", "1286883c001005010000004e0c4e0c080708076400000001000000072f0000000000000000000000000000001b000000000000000000000000000000000000"),
    ("in", "12f5c83c00100601000000ba134e0c080708076400000000000000073000000000000000000000000000000006000000000000044c00000000000000000000"),
    ("in", "125bb23c00100701000000261b4e0c080708076400000001000000000000000000000000000000000000000015000000000000044e00000000000000000000"),
    # asking for a ninth key, and being told there isn't one
    ("out", "12351a040010080000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"),
    ("in", "12355a044010080000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"),
    # and then the page set key 8 to p, by sending back the record it had
    # just read with one byte changed. Which is what we do.
    ("out", "125bc53c00100701000000261b4e0c080708076400000001000000001300000000000000000000000000000015000000000000044e00000000000000000000"),
]

LIVE = [bytes.fromhex(h) for d, h in STARTUP if d == "in" and
        bytes.fromhex(h)[TABLE_AT] == 0x10 and bytes.fromhex(h)[LEN_AT] == 0x3C]

# A third capture: the page setting key 8 to each of four volume and
# brightness keys in turn, with the log cleared first. All four differ
# from each other in byte 27 and nothing else, and all four set byte 23
# to 0x03 where the key had been 0x01. That pair of facts is what makes
# byte 23 the key type rather than drifting state.
CONSUMER_CAPTURE = {
    "volumeup": "1267b23c00100701000000261b4e0c0807080764000000030000000a0000000000000000000000000000000015000000000000044e00000000000000000000",
    "volumedown": "1268b23c00100701000000261b4e0c0807080764000000030000000b0000000000000000000000000000000015000000000000044e00000000000000000000",
    "brightnessup": "125eb23c00100701000000261b4e0c080708076400000003000000010000000000000000000000000000000015000000000000044e00000000000000000000",
    "brightnessdown": "125fb23c00100701000000261b4e0c080708076400000003000000020000000000000000000000000000000015000000000000044e00000000000000000000",
}


def _records():
    out = {}
    for h in CAPTURED:
        b = bytes.fromhex(h)
        out.setdefault(b[KEY_AT], b)       # first sighting of each key
    return out


RECORDS = _records()

USAGES = {c: 4 + i for i, c in enumerate("abcdefghijklmnopqrstuvwxyz")}
USAGES.update({str(d): 30 + i for i, d in enumerate("1234567890")})
USAGES.update({
    "enter": 40, "esc": 41, "backspace": 42, "tab": 43, "space": 44,
    "minus": 45, "equal": 46, "leftbracket": 47, "rightbracket": 48,
    "backslash": 49, "semicolon": 51, "quote": 52, "grave": 53,
    "comma": 54, "period": 55, "slash": 56, "capslock": 57,
    "printscreen": 70, "insert": 73, "home": 74, "pageup": 75,
    "delete": 76, "end": 77, "pagedown": 78,
    "right": 79, "left": 80, "down": 81, "up": 82,
    "numlock": 83, "numpadslash": 84, "numpadstar": 85,
    "numpadminus": 86, "numpadplus": 87, "numpadenter": 88, "numpaddot": 99,
})
for _i in range(1, 13):
    USAGES[f"f{_i}"] = 57 + _i
for _i in range(1, 10):
    USAGES[f"numpad{_i}"] = 0x58 + _i
USAGES["numpad0"] = 0x62

# Standard HID modifier bits. The pad uses them unchanged.
MODIFIERS = {"ctrl": 0x01, "shift": 0x02, "alt": 0x04, "meta": 0x08,
             "super": 0x08, "win": 0x08,
             "rctrl": 0x10, "rshift": 0x20, "ralt": 0x40, "rmeta": 0x80}


def parse_combo(text):
    """'ctrl+shift+a' -> (0x03, 0x04). A bare modifier gives keycode 0."""
    mods, usage = 0, 0
    for part in text.lower().replace(" ", "").split("+"):
        if not part:
            continue
        if part in MODIFIERS:
            mods |= MODIFIERS[part]
        elif part in USAGES:
            usage = USAGES[part]
        else:
            raise KeyError(f"don't know {part!r}")
    return mods, usage


def checksum(payload):
    """
    Sum the whole 64 byte report as little endian 16 bit words with the
    checksum field zeroed. No magic constant: this reproduces all ten
    captured packets exactly.
    """
    raw = bytearray([REPORT_ID]) + bytearray(payload)
    raw[2] = raw[3] = 0                      # the checksum's own two bytes
    if len(raw) % 2:
        raw.append(0)
    total = sum(raw[i] | (raw[i + 1] << 8) for i in range(0, len(raw), 2))
    return total & 0xFFFF


def seal(payload):
    """Put the right checksum into a payload and hand it back."""
    out = bytearray(payload)
    c = checksum(out)
    out[CHECK_AT] = c & 0xFF
    out[CHECK_AT + 1] = (c >> 8) & 0xFF
    return bytes(out)


def verify(payload):
    return payload[CHECK_AT] | (payload[CHECK_AT + 1] << 8) == checksum(payload)


def kind_of(record):
    """What sort of key this is: 'keyboard', 'consumer', or 'unknown'."""
    return KINDS.get(record[KIND_AT], "unknown")


def read_binding(record):
    """
    (kind, a, b) from a record, where what a and b mean follows the kind.

      keyboard  (modifier bitmask, HID usage)
      consumer  (consumer code, name or None)
      unknown   (byte 23, byte 27) and nothing else to say

    Returning the kind rather than guessing is the whole point: three keys
    on one real pad are type 0x80, and reading those as a modifier made
    them look like a bare "ctrl+shift" that nobody had set.
    """
    kind = kind_of(record)
    if kind == "keyboard":
        return kind, record[MOD_AT], record[KEYCODE_AT]
    if kind == "consumer":
        code = record[MOD_AT]
        return kind, code, CONSUMER.get(code)
    return kind, record[KIND_AT], record[MOD_AT]


def patch_binding(record, mods, usage):
    """
    One key's record holding a keyboard shortcut instead, resealed.

    record must be that key's own record, because bytes 11 to 18 are where
    that key sits on the pad face and other bytes are its own state. Pass
    another key's record and you move this key on top of that one.

    Byte 23 is set to the keyboard kind. If the key was already a keyboard
    key its low bit is kept, since that bit shows up either way and the
    vendor's page leaves it alone when it changes a letter.
    """
    out = bytearray(record)
    was = out[KIND_AT]
    out[KIND_AT] = (was & 0x01) if was in KEYBOARD_KINDS else KIND_KEYBOARD
    out[MOD_AT] = mods
    out[KEYCODE_AT] = usage
    return seal(out)


def patch_consumer(record, code):
    """
    One key's record holding a volume or brightness key, resealed.

    code is a key of CONSUMER, or one of its names. Byte 23 becomes 0x03
    and byte 28 goes to zero, which is exactly what the capture of the
    page doing this shows.
    """
    if isinstance(code, str):
        if code not in CONSUMER_BY_NAME:
            raise KeyError(f"no captured code for {code!r}; known: "
                           f"{', '.join(sorted(CONSUMER_BY_NAME))}")
        code = CONSUMER_BY_NAME[code]
    out = bytearray(record)
    out[KIND_AT] = KIND_CONSUMER
    out[MOD_AT] = code
    out[KEYCODE_AT] = 0
    return seal(out)


def patch_keycode(record, usage):
    """A plain key with no modifier."""
    return patch_binding(record, 0, usage)


def is_heartbeat(payload):
    """The status report the pad sends unasked, about once a second."""
    return bool(payload) and payload[0] == 0x00


def report(payload):
    """The 64 bytes to hand to a hidraw write."""
    return bytes([REPORT_ID]) + bytes(payload)


# ------------------------------------------------------ reading the pad
#
# A capture of the configurator starting up gave this away. Ask with a
# four byte payload naming a table and an index, get the row back. Walk
# the index up from zero and the pad tells you when to stop, so the key
# count does not have to be guessed or configured anywhere.


def read_request(table, index=0):
    """The payload that asks for one row of one table."""
    out = bytearray(63)
    out[0] = CMD
    out[LEN_AT] = REQUEST_LEN
    out[FLAG_AT] = FLAGS.get(table, 0x00)
    out[TABLE_AT] = table
    out[KEY_AT] = index
    return seal(out)


def parse_reply(payload):
    """
    {table, index, flags, data, end} from anything the pad sends back.

    data is only the meaningful part: byte 3 says how far it runs. end is
    True when the index does not exist, which is how you find out how many
    keys a pad has.
    """
    p = bytes(payload)
    if len(p) < DATA_AT or p[0] != CMD:
        raise ValueError("not a 0x12 report")
    size = p[LEN_AT]
    return {"table": p[TABLE_AT], "index": p[KEY_AT], "flags": p[FLAG_AT],
            "data": p[FLAG_AT:FLAG_AT + size], "payload": p,
            "end": bool(p[FLAG_AT] & NO_SUCH_INDEX)}


def is_key_record(payload):
    """Is this 63 bytes a key record, rather than a short reply or noise?"""
    p = bytes(payload)
    return (len(p) >= DATA_AT and p[0] == CMD and p[TABLE_AT] == TABLE_KEYS
            and p[LEN_AT] == RECORD_LEN and not p[FLAG_AT] & NO_SUCH_INDEX)


def key_geometry(record):
    """
    (x, y, w, h) of one key on the pad face, from its record.

    The unit is arbitrary but consistent. What it is good for is working
    out the shape of a pad nobody has told us about: group the keys by y
    to get the rows.
    """
    u16 = lambda o: record[o] | (record[o + 1] << 8)
    return u16(11), u16(13), u16(15), u16(17)


def grid_from_records(records):
    """
    (rows, cols) worked out from where the keys actually are.

    Beats guessing from the key count, which cannot tell a 4 by 2 from a
    2 by 4 or an 8 by 1.
    """
    rows = sorted({key_geometry(r)[1] for r in records})
    cols = sorted({key_geometry(r)[0] for r in records})
    return len(rows) or 1, len(cols) or 1


def device_name(payload):
    """
    The model name out of a table 0x01 reply. UTF-16LE, zero padded.

    The declared length can land on an odd byte, which would leave half a
    character on the end, so trim to even and then cut at the first NUL
    rather than trusting the padding.
    """
    p = bytes(payload)
    size = max(0, p[LEN_AT] - 3)
    raw = p[DATA_AT:DATA_AT + size - (size % 2)]
    return raw.decode("utf-16-le", "replace").split("\x00")[0].strip()


def tables_offered(payload):
    """
    Which tables a pad admits to having, from a table 0x00 reply.

    Only used to sanity check that 0x10 is there before trusting the rest.
    """
    p = bytes(payload)
    body = p[FLAG_AT:FLAG_AT + p[LEN_AT]]
    seen, out = set(), []
    for b in body[10:]:                      # the list sits after a header
        if b and b not in seen:
            seen.add(b)
            out.append(b)
    return out


# ------------------------------------------------------- backup files
#
# The configurator's "backup" button writes a .sayobak. Inside it, from
# offset 102, are the pad's eight key records, 62 bytes each. They are the
# same layout as a write payload from byte 11 on, which is the part we
# cannot invent, so a backup is a perfectly good substitute for reading the
# records off the pad.
#
# Rebuilding key 1's captured write from its backup record comes out byte
# for byte identical, which is what makes this trustworthy.

BACKUP_MAGIC = b"Sayo Device Backup File"
BACKUP_START = 102
BACKUP_STRIDE = 62
KEYS_IN_BACKUP = 8


def read_backup(data):
    """
    [{key, x, y, w, h, mods, usage, record}] from a .sayobak, one per key.

    x and y are the key's position on the pad face and w and h its size, in
    whatever unit the firmware uses. On an 8 key pad they come out as a 4 by
    2 grid with a pitch of 1900 and a size of 1800.
    """
    if hasattr(data, "read_bytes"):
        data = data.read_bytes()
    elif isinstance(data, str):
        data = Path(data).read_bytes()
    if not data.startswith(BACKUP_MAGIC):
        raise ValueError("not a Sayo backup file")
    out = []
    for i in range(KEYS_IN_BACKUP):
        off = BACKUP_START + i * BACKUP_STRIDE
        rec = data[off:off + BACKUP_STRIDE]
        if len(rec) < BACKUP_STRIDE:
            break
        u16 = lambda o: rec[o] | (rec[o + 1] << 8)
        out.append({"key": i, "x": u16(11), "y": u16(13),
                    "w": u16(15), "h": u16(17),
                    "mods": rec[MOD_AT], "usage": rec[KEYCODE_AT],
                    "record": rec})
    return out


def payload_from_record(record, key, mods, usage):
    """
    A write payload for one key, built from that key's backup record.

    The header is fixed, bytes 11 onward come from the record, and only the
    binding changes. Checked against the captures: key 1 comes out byte for
    byte identical to what the vendor's page sent.
    """
    out = bytearray(63)
    out[0] = CMD_WRITE_KEY
    out[3] = 0x3C
    out[5] = 0x10
    out[6] = key
    out[7] = 0x01
    out[11:62] = record[11:62]
    return patch_binding(out, mods, usage)


def describe_record(record):
    """What one key does, in words, whatever kind of key it is."""
    kind, a, b = read_binding(record)
    if kind == "keyboard":
        return describe(a, b)
    if kind == "consumer":
        return b or f"an uncaptured volume or brightness code, 0x{a:02x}"
    return f"a key type we haven't decoded, 0x{a:02x} with 0x{b:02x}"


def describe(mods, usage):
    """'ctrl+shift+a' from a modifier bitmask and a usage code."""
    names = [n for n, bit in (("ctrl", 0x01), ("shift", 0x02), ("alt", 0x04),
                              ("meta", 0x08), ("rctrl", 0x10), ("rshift", 0x20),
                              ("ralt", 0x40), ("rmeta", 0x80)) if mods & bit]
    by_code = {v: k for k, v in sorted(USAGES.items())}
    if usage:
        names.append(by_code.get(usage, f"0x{usage:02x}"))
    return "+".join(names) or "nothing"


# ------------------------------------------------------------- self test


if __name__ == "__main__":
    bad = 0
    for h in CAPTURED:
        b = bytes.fromhex(h)
        if seal(b) != b or not verify(b):
            bad += 1
            print(f"  MISMATCH key={b[KEY_AT]} stored={b[1]:02x}{b[2]:02x} "
                  f"computed={seal(b)[1]:02x}{seal(b)[2]:02x}")
    print(f"{len(CAPTURED) - bad}/{len(CAPTURED)} captured packets reproduced exactly")

    for key, rec in sorted(RECORDS.items()):
        assert len(rec) == 63, f"key {key} record is {len(rec)} bytes, want 63"
        assert verify(rec), f"stored record for key {key} fails its own checksum"
        got = patch_keycode(rec, USAGES["z"])
        assert verify(got) and got[KEYCODE_AT] == USAGES["z"]
    print(f"{len(RECORDS)} stored key records verify and re-seal cleanly")

    # the two modifier captures, rebuilt from key 8's record
    for combo, want in (("shift", "1258643c"), ("meta", "125e643c")):
        mods, usage = parse_combo(combo)
        built = patch_binding(RECORDS[7], mods, usage)
        assert built.hex().startswith(want), f"{combo}: {built[:4].hex()} != {want}"
    print("left shift and meta captures rebuilt from key 8's record")

    for combo in ("ctrl+a", "ctrl+shift+t", "meta+w", "alt+a"):
        mods, usage = parse_combo(combo)
        out = patch_binding(RECORDS[0], mods, usage)
        assert verify(out)
    print("modifier combinations build and verify")

    # ------------------------------------------------ the startup capture

    for direction, h in STARTUP:
        b = bytes.fromhex(h)
        assert len(b) == 63, f"{h[:8]} is {len(b)} bytes"
        assert verify(b), f"{h[:8]} fails its own checksum"
    print(f"{len(STARTUP)} startup packets verify")

    # our read_request() against the three the page actually sent
    for table, index, want in ((TABLE_DIRECTORY, 0, "122512040000"),
                               (TABLE_NAME, 0, "12261e040c01"),
                               (TABLE_KEYS, 0, "123512040010"),
                               (TABLE_KEYS, 8, "12351a040010")):
        got = read_request(table, index).hex()
        assert got.startswith(want), f"table {table:#04x}: {got[:12]} != {want}"
    print("read requests match the ones the vendor's page sends")

    end = parse_reply(bytes.fromhex(
        "12355a044010080000000000000000000000000000000000000000000000000000"
        "0000000000000000000000000000000000000000000000000000000000000000"[:126]))
    assert end["end"] and end["index"] == 8
    assert len(LIVE) == 8 and not any(parse_reply(r)["end"] for r in LIVE)
    print(f"the pad reports {len(LIVE)} keys and says so when asked for a ninth")

    name = device_name(bytes.fromhex(
        [h for d, h in STARTUP if d == "in" and bytes.fromhex(h)[TABLE_AT] == 1][0]))
    assert name == "SayoDevice 2x4V RGB", repr(name)
    print(f"model name reads back as {name!r}")

    assert TABLE_KEYS in tables_offered(bytes.fromhex(STARTUP[1][1]))
    rows, cols = grid_from_records(LIVE)
    assert (rows, cols) == (2, 4), (rows, cols)
    print(f"geometry puts the keys in a {cols} by {rows} grid")

    # the page read key 8 then wrote it. Rebuild that write from that read.
    rebuilt = payload_from_record(LIVE[7], 7, 0x00, USAGES["p"])
    assert rebuilt == bytes.fromhex(STARTUP[-1][1]), "read-modify-write diverged"
    print("the page's own write rebuilt byte for byte from the record it read")

    # ------------------------------------------- volume and brightness

    before = LIVE[7]
    assert before[KIND_AT] == 0x01, f"key 8 started at {before[KIND_AT]:#04x}"
    for name, want in CONSUMER_CAPTURE.items():
        built = patch_consumer(before, name)
        assert built == bytes.fromhex(want), (
            f"{name}: {[n for n in range(63) if built[n] != bytes.fromhex(want)[n]]}")
    print(f"all {len(CONSUMER_CAPTURE)} volume and brightness writes rebuilt exactly")

    kinds = {bytes.fromhex(h)[KIND_AT] for h in CONSUMER_CAPTURE.values()}
    assert kinds == {KIND_CONSUMER}, kinds
    print("and each one set byte 23 to 0x03 where the key had been 0x01, "
          "so byte 23 is the key type")

    for name, h in CONSUMER_CAPTURE.items():
        kind, code, got = read_binding(bytes.fromhex(h))
        assert (kind, got) == ("consumer", name), (kind, got, name)
    print("they read back as the names they were set to")

    # a kind we have never captured must not read as a keyboard shortcut
    odd = bytearray(LIVE[0])
    odd[KIND_AT] = 0x80
    assert kind_of(odd) == "unknown"
    assert "haven't decoded" in describe_record(odd)
    print("an uncaptured key type reads as unknown rather than a bare modifier")

    # switching a key back to a shortcut must clear the consumer type
    back = patch_binding(bytes.fromhex(CONSUMER_CAPTURE["volumeup"]), 0x01,
                         USAGES["c"])
    assert back[KIND_AT] == KIND_KEYBOARD and verify(back)
    assert read_binding(back) == ("keyboard", 0x01, USAGES["c"])
    print("and setting a shortcut on a volume key clears the type back")

    for i, rec in enumerate(LIVE):
        x, y, w, h = key_geometry(rec)
        print(f"  key {i+1}: at ({x:>5},{y:>5}) size {w}x{h}  "
              f"[{kind_of(rec)}]  ->  {describe_record(rec)}")

    # a backup, if one is sitting next to this file
    import glob
    for path in sorted(glob.glob("*.sayobak")) + sorted(glob.glob("backup.bin")):
        keys = read_backup(Path(path))
        print(f"\n{path}: {len(keys)} key records")
        cols = len({k["x"] for k in keys})
        print(f"  pad is {cols} across by {len(keys)//cols} down")
        for k in keys:
            print(f"  key {k['key']+1}: at ({k['x']:>5},{k['y']:>5}) "
                  f"size {k['w']}x{k['h']}  [{kind_of(k['record'])}]  ->  "
                  f"{describe_record(k['record'])}")
        rebuilt = payload_from_record(keys[0]["record"], 0, 0, USAGES["a"])
        assert verify(rebuilt)
        assert rebuilt == RECORDS[0], "key 1 should rebuild to its captured write"
        print("  key 1 rebuilt from the backup matches its captured write exactly")
        break
