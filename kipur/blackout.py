#!/usr/bin/env python3
"""Opaque black fullscreen window on every monitor until a deadline.

Wayland has no per-monitor DPMS a client may drive, and gnome-shell's Eval
endpoint is locked, so the only way to black out every output from outside the
shell is a real fullscreen window per monitor. Nothing is suspended, killed or
paused: this only covers the screens.
"""
import json
import os
import subprocess
import sys
import time

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Pango  # noqa: E402

STATE = os.path.expanduser("~/.cache/kipur/state.json")
STOP = os.path.expanduser("~/.cache/kipur/stop")
HINT_SECONDS = 20
# Deliberate exits only. A plain-Escape route was tried and a stray burst of
# keystrokes lifted the blackout by accident within seconds, which is exactly
# what a blackout must not do.


def deadline():
    """Epoch to stay black until. No state, or a deadline already past, means
    there is no blackout to hold: exit rather than invent one, so a stray start
    (a login, a restart) can never black the screens out of nowhere."""
    try:
        with open(STATE) as fh:
            until = float(json.load(fh)["until"])
    except Exception:
        sys.exit(0)
    if until <= time.time():
        sys.exit(0)
    return until


class Blackout:
    def __init__(self):
        self.until = deadline()
        self.windows = []
        self.escapes = []
        self.display = Gdk.Display.get_default()
        self.build()
        self.display.connect("monitor-added", lambda *_: self.rebuild())
        self.display.connect("monitor-removed", lambda *_: self.rebuild())
        GLib.timeout_add_seconds(2, self.tick)
        GLib.timeout_add_seconds(HINT_SECONDS, self.hide_hint)

    # -- windows ----------------------------------------------------------
    def build(self):
        screen = Gdk.Screen.get_default()
        n = self.display.get_n_monitors()
        for i in range(n):
            win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
            win.set_title("Yom Kippur blackout")
            win.set_decorated(False)
            win.set_app_paintable(True)
            win.set_keep_above(True)
            win.set_skip_taskbar_hint(True)
            win.set_skip_pager_hint(True)
            win.set_accept_focus(True)
            win.connect("delete-event", lambda *_: True)   # unclosable
            win.connect("key-press-event", self.on_key)

            box = Gtk.EventBox()
            box.override_background_color(
                Gtk.StateFlags.NORMAL, Gdk.RGBA(0, 0, 0, 1))
            label = Gtk.Label()
            label.set_justify(Gtk.Justification.CENTER)
            end = time.strftime("%a %H:%M", time.localtime(self.until))
            label.set_markup(
                '<span foreground="#1c1c1c" size="13000">'
                "גמר חתימה טובה\n\n"
                "screens stay dark until %s\n"
                "everything running keeps running\n\n"
                "Ctrl+Alt+Shift+K  ends it early"
                "</span>" % end)
            label.set_line_wrap(True)
            attrs = Pango.AttrList()
            label.set_attributes(attrs)
            box.add(label)
            win.add(box)

            win.fullscreen_on_monitor(screen, i)
            win.fullscreen()
            win.show_all()
            win.present()
            self.windows.append((win, label))

    def rebuild(self):
        for win, _ in self.windows:
            win.destroy()
        self.windows = []
        self.build()

    def hide_hint(self):
        for _, label in self.windows:
            label.hide()
        return False

    # -- input ------------------------------------------------------------
    def on_key(self, _win, event):
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        shift = event.state & Gdk.ModifierType.SHIFT_MASK
        key = Gdk.keyval_name(event.keyval) or ""
        if ctrl and shift and key.lower() == "q":
            self.finish()
        return True     # swallow every keystroke; nothing reaches the desktop

    # -- loop -------------------------------------------------------------
    def tick(self):
        if os.path.exists(STOP) or time.time() >= self.until:
            self.finish()
            return False
        # Re-assert over anything that opened on top of us.
        for win, _ in self.windows:
            if not win.is_visible():
                win.show_all()
            gdk_win = win.get_window()
            if gdk_win is not None:
                state = gdk_win.get_state()
                if not state & Gdk.WindowState.FULLSCREEN:
                    win.fullscreen()
        return True

    def finish(self):
        # Run the restore in a unit of its own: this process lives inside the
        # kipur-blackout cgroup, and `kipur off` stops that unit, which would
        # kill a plain child half way through putting the settings back.
        subprocess.Popen(
            ["systemd-run", "--user", "--collect", "--quiet",
             "--unit=kipur-restore-%d" % int(time.time()),
             os.path.expanduser("~/.local/bin/kipur"), "off"],
            start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        Gtk.main_quit()


def main():
    if os.path.exists(STOP):
        os.remove(STOP)
    Blackout()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
