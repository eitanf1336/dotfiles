import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

// Helper that takes the monitor's actual light down as well as painting it
// black. An opaque black overlay still leaves the backlight at full, so the
// panel glows dark grey; screen-dark drops the laptop backlight or the
// monitor's own DDC/CI brightness to zero. It is spawned, never waited on:
// a DDC conversation takes a second or two and the overlay must be instant.
// A DisplayLink screen answers neither, so there it is a no-op and the black
// pixels are the floor.
const SCREEN_DARK = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'screen-dark']);

function screenDark(args) {
    try {
        if (!GLib.file_test(SCREEN_DARK, GLib.FileTest.IS_EXECUTABLE))
            return;
        Gio.Subprocess.new([SCREEN_DARK, ...args], Gio.SubprocessFlags.NONE);
    } catch (e) {
        logError(e, 'Blackout Screen: screen-dark failed');
    }
}

// Toggle an opaque black overlay over the monitor the pointer is currently on.
// On Wayland (GNOME/Mutter) a normal app cannot pin itself on top of a chosen
// output, so the blackout is drawn as a Shell overlay actor — the same
// technique used by the DisplayLink Night Light extension.
export default class BlackoutScreen extends Extension {
    enable() {
        this._settings = this.getSettings();
        this._overlays = new Map(); // monitor index -> St.Widget
        this._unredirectDisabled = false;

        // If the monitor layout changes, indices become invalid — drop every
        // overlay so we never leave an orphan covering the wrong output.
        this._monitorsChangedId =
            Main.layoutManager.connect('monitors-changed', () => this._clearAll());

        // Let any fullscreen window (Sunrise Alarm, a video, a game) punch
        // through a blackout: as soon as a monitor enters fullscreen, drop its
        // overlay so the fullscreen content is actually visible. Without this,
        // blacking out a screen would hide e.g. the sunrise light behind the
        // overlay while its audio still played.
        this._fullscreenId =
            global.display.connect('in-fullscreen-changed', () => this._syncFullscreen());

        Main.wm.addKeybinding(
            'toggle-blackout',
            this._settings,
            Meta.KeyBindingFlags.NONE,
            Shell.ActionMode.ALL,
            () => this._toggle());
    }

    disable() {
        Main.wm.removeKeybinding('toggle-blackout');

        if (this._monitorsChangedId) {
            Main.layoutManager.disconnect(this._monitorsChangedId);
            this._monitorsChangedId = null;
        }

        if (this._fullscreenId) {
            global.display.disconnect(this._fullscreenId);
            this._fullscreenId = null;
        }

        this._clearAll();
        this._settings = null;
    }

    _syncFullscreen() {
        // Clear the blackout on any monitor that now has a fullscreen window.
        for (const idx of [...this._overlays.keys()]) {
            if (global.display.get_monitor_in_fullscreen(idx)) {
                this._overlays.get(idx).destroy();
                this._overlays.delete(idx);
                const m = Main.layoutManager.monitors[idx];
                if (m)
                    screenDark(['--at', `${m.x},${m.y}`, 'off']);
            }
        }
        this._syncUnredirect();
    }

    // Mutter bypasses the compositor for a window that covers its whole monitor
    // and is opaque (Chrome app windows maximised on a monitor with no panel or
    // dock are the usual case). While that happens the window's buffer goes
    // straight to the output, so Shell overlay actors on that monitor are never
    // painted: the blackout would be created, swallow the pointer, and still
    // look like nothing happened. Holding unredirect off for as long as any
    // overlay exists forces the compositor back into the path.
    _syncUnredirect() {
        const wanted = this._overlays.size > 0;
        if (wanted === this._unredirectDisabled)
            return;

        const compositor = global.compositor;
        if (compositor?.disable_unredirect) {
            if (wanted)
                compositor.disable_unredirect();
            else
                compositor.enable_unredirect();
        } else if (Meta.disable_unredirect_for_display) {
            // Shell 45 and earlier.
            if (wanted)
                Meta.disable_unredirect_for_display(global.display);
            else
                Meta.enable_unredirect_for_display(global.display);
        } else {
            return;
        }

        this._unredirectDisabled = wanted;
    }

    _toggle() {
        // Monitor under the pointer == "the screen you're on".
        const idx = global.display.get_current_monitor();
        if (idx < 0)
            return;

        // Already blacked out? Restore it. An overlay that lost its parent is a
        // stale bookkeeping entry, not a live blackout: drop it and fall through
        // to build a new one, so a press never turns into a silent no-op.
        const existing = this._overlays.get(idx);
        if (existing) {
            this._overlays.delete(idx);
            if (existing.get_parent()) {
                existing.destroy();
                const m = Main.layoutManager.monitors[idx];
                if (m)
                    screenDark(['--at', `${m.x},${m.y}`, 'off']);
                this._syncUnredirect();
                return;
            }
        }

        const monitor = Main.layoutManager.monitors[idx];
        if (!monitor)
            return;

        const overlay = new St.Widget({
            style: 'background-color: #000000;',
            reactive: true, // swallow pointer input so the screen acts "off"
            can_focus: false,
            track_hover: false,
            x: monitor.x,
            y: monitor.y,
            width: monitor.width,
            height: monitor.height,
        });

        // Absorb pointer events on this monitor rather than letting them reach
        // the now-invisible windows underneath.
        const swallow = () => Clutter.EVENT_STOP;
        overlay.connect('button-press-event', swallow);
        overlay.connect('button-release-event', swallow);
        overlay.connect('scroll-event', swallow);

        Main.layoutManager.uiGroup.add_child(overlay);
        Main.layoutManager.uiGroup.set_child_above_sibling(overlay, null);

        this._overlays.set(idx, overlay);
        screenDark(['--at', `${monitor.x},${monitor.y}`, 'on']);
        this._syncUnredirect();
    }

    _clearAll() {
        const had = this._overlays.size > 0;
        for (const overlay of this._overlays.values())
            overlay.destroy();
        this._overlays.clear();
        // The monitor layout may already have changed under us, so a position
        // would no longer resolve: restore by what was actually dimmed.
        if (had)
            screenDark(['restore-all']);
        this._syncUnredirect();
    }
}
