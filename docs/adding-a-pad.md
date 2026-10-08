# Adding a pad the app doesn't know yet

If MacroPad finds your pad but says it isn't supported, this is the whole
process. It takes one command and one issue.

## Start here: ask the pad

Install MacroPad, plug your pad in, and run:

```
macropad detect
```

On most pads in this family that's the whole job. It asks the pad how many keys and knobs it has, reads back what's currently bound, and prints a report. Paste that into [an issue](https://github.com/Probler-Yt/MacroPad/issues) and your pad gets added to the known list.

The app offers the same thing: when it sees a pad it doesn't recognise, the panel has an **Ask the pad what it is** button.

## How it decides

Detection is read only, and the pad has to pass two tests before the app will write anything to it:

1. It answers the `0xFB` query with a sensible key and knob count.
2. It then reports a full layer, describing exactly the control slots that count implies.

A pad from a different family fails one of those, and the app leaves it alone rather than guessing.

The pad reports how many keys and knobs it has, but not how they're arranged, so the first guess at rows and columns may be wrong. Fix it with [Edit layout](#-if-the-drawing-doesnt-match-your-pad) and the drawing will match your hardware.

## If it doesn't answer

Some pads in this family speak an older protocol and won't answer. Working those out needs a capture of the vendor software, the same process used for this one. You'll need `MINI_KEYBOARD.exe` and Wine.

#### Capture what the vendor software sends

1. **See what your pad is:**
   ```
   python3 ~/.local/share/macropad/app/macropad-probe.py
   ```
   This only reads. It lists your pad's ID and its USB interfaces.

2. **Start the capture** (it watches USB traffic; it never sends anything):
   ```
   cd ~/.local/share/macropad/app
   sudo python3 macropad-capture.py
   ```

3. **In a second terminal**, open the vendor app with Wine:
   ```
   wine MINI_KEYBOARD.exe
   ```

4. In the vendor app, set **key 1 to the letter `a`** and click its save/apply button. Then set **each knob's turn left, press and turn right** to different letters, and save again.

5. Go back to the first terminal and press **`Ctrl+C`**. You now have a file called `macropad-capture.txt`.

6. **[Open an issue](https://github.com/Probler-Yt/MacroPad/issues)** with that file, your `macropad-probe.py` output, and a photo of your pad. That's genuinely all it takes to get your pad supported.

---
