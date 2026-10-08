"""Linux GUI for Holtek-family USB macro pads. GPL-3.0."""

# The one place the version is written down. The CLI's --version, the app's
# About box and the bug report template all read it from here, so a release
# is one line to change and the tag can never disagree with what ships.
#
# Semver, and the rule used so far: major when the idea of how the app works
# changes, minor for new hardware or features, patch for fixes.
#
#   1.x    write only, because these pads were assumed to be unreadable
#   2.0.0  they can be read, plus detection, actions and themes
#   2.1.0  a second protocol family (SayoDevice), 15 key pads, theme styles
__version__ = "2.1.0"
