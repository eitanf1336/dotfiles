import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';
import Clutter from 'gi://Clutter';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

// Toggle an opaque black overlay over the monitor the pointer is currently on.
// On Wayland (GNOME/Mutter) a normal app cannot pin itself on top of a chosen
// output, so the blackout is drawn as a Shell overlay actor — the same
// technique used by the DisplayLink Night Light extension.
export default class BlackoutScreen extends Extension {
    enable() {
        this._settings = this.getSettings();
        this._overlays = new Map(); // monitor index -> St.Widget

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
            }
        }
    }

    _toggle() {
        // Monitor under the pointer == "the screen you're on".
        const idx = global.display.get_current_monitor();
        if (idx < 0)
            return;

        // Already blacked out? Restore it.
        if (this._overlays.has(idx)) {
            this._overlays.get(idx).destroy();
            this._overlays.delete(idx);
            return;
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
    }

    _clearAll() {
        for (const overlay of this._overlays.values())
            overlay.destroy();
        this._overlays.clear();
    }
}
