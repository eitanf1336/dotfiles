import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import GLib from 'gi://GLib';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const KEY = 'tile-new-terminal';

// Grab-op flag that Mutter ORs into the op for unconstrained moves.
const GRAB_OP_WINDOW_FLAG_UNCONSTRAINED = 1024;

export default class TerminalTilerExtension extends Extension {
    enable() {
        this._settings = this.getSettings();

        // monitorIndex -> ordered array of Meta.Window (one batch per monitor).
        this._batches = new Map();
        // monitors waiting for a freshly-spawned terminal window to appear.
        this._pending = [];

        Main.wm.addKeybinding(
            KEY,
            this._settings,
            Meta.KeyBindingFlags.IGNORE_AUTOREPEAT,
            Shell.ActionMode.NORMAL,
            this._onActivate.bind(this)
        );

        // A new window appeared — claim it if we asked for a terminal.
        global.display.connectObject(
            'window-created',
            (_disp, win) => this._onWindowCreated(win),
            this
        );

        // The user finished dragging/resizing a window with the mouse or
        // keyboard. If it was one of ours, eject it and re-flow the rest.
        // (Our own programmatic move_resize_frame calls never start a grab op,
        // so this only ever fires for genuine user actions.)
        global.display.connectObject(
            'grab-op-end',
            (_disp, win) => this._onGrabOpEnd(win),
            this
        );

        // Re-flow when monitors are added/removed so stale geometry is fixed.
        Main.layoutManager.connectObject(
            'monitors-changed',
            () => this._retileAll(),
            this
        );
    }

    disable() {
        Main.wm.removeKeybinding(KEY);
        global.display.disconnectObject(this);
        Main.layoutManager.disconnectObject(this);

        // Drop our handlers from every tracked window.
        for (const arr of this._batches.values())
            for (const win of arr)
                win.disconnectObject(this);

        this._batches = null;
        this._pending = null;
        this._settings = null;
    }

    // ----- core action -------------------------------------------------------

    _onActivate() {
        const focus = global.display.focus_window;

        // A stray terminal is focused and not yet managed → absorb it.
        if (this._isTerminal(focus) && this._monitorOf(focus) === null) {
            const monitor = focus.get_monitor();
            this._add(monitor, focus);
            this._tile(monitor);
            return;
        }

        // Otherwise spawn a fresh terminal onto the focused monitor.
        const monitor = focus
            ? focus.get_monitor()
            : global.display.get_current_monitor();
        this._spawnInto(monitor);
    }

    _spawnInto(monitor) {
        this._pending.push(monitor);

        const cmd = this._settings.get_string('terminal-command');
        try {
            const [ok, argv] = GLib.shell_parse_argv(cmd);
            if (ok)
                GLib.spawn_async(null, argv, null,
                    GLib.SpawnFlags.SEARCH_PATH, null);
        } catch (e) {
            logError(e, `Terminal Tiler: failed to launch "${cmd}"`);
            this._pending.pop();
        }
    }

    _onWindowCreated(win) {
        if (!this._pending.length)
            return;
        if (win.get_window_type() !== Meta.WindowType.NORMAL)
            return;

        // Wait until the window is actually mapped before we size it, so
        // unmaximize/move_resize_frame take effect on a real frame.
        const actor = win.get_compositor_private();
        const place = () => {
            if (!this._pending.length || !this._isAlive(win))
                return;
            // Only claim it if it looks like our terminal (best effort).
            if (!this._isTerminal(win))
                return;
            const monitor = this._pending.shift();
            this._add(monitor, win);
            this._tile(monitor);
        };

        if (actor) {
            actor.connectObject('first-frame',
                () => GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
                    place();
                    return GLib.SOURCE_REMOVE;
                }), this);
        } else {
            GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
                place();
                return GLib.SOURCE_REMOVE;
            });
        }
    }

    _onGrabOpEnd(win) {
        const monitor = this._monitorOf(win);
        if (monitor === null)
            return;
        // User moved/resized a tiled window: eject it, keep its new geometry,
        // and re-flow whatever remains on that monitor.
        this._remove(win, monitor);
        this._tile(monitor);
    }

    // ----- batch bookkeeping -------------------------------------------------

    _add(monitor, win) {
        let arr = this._batches.get(monitor);
        if (!arr) {
            arr = [];
            this._batches.set(monitor, arr);
        }
        if (arr.includes(win))
            return;
        arr.push(win);
        // Forget the window when it closes, then re-flow its monitor.
        win.connectObject('unmanaging', () => {
            this._remove(win, monitor);
            this._tile(monitor);
        }, this);
    }

    _remove(win, monitor) {
        const arr = this._batches.get(monitor);
        if (!arr)
            return;
        const i = arr.indexOf(win);
        if (i >= 0)
            arr.splice(i, 1);
        win.disconnectObject(this);
        if (arr.length === 0)
            this._batches.delete(monitor);
    }

    // Monitor index whose batch holds `win`, or null.
    _monitorOf(win) {
        if (!win)
            return null;
        for (const [monitor, arr] of this._batches)
            if (arr.includes(win))
                return monitor;
        return null;
    }

    // ----- tiling ------------------------------------------------------------

    _tile(monitor) {
        const arr = this._batches.get(monitor);
        if (!arr)
            return;

        // Prune windows that died or got dragged onto another monitor.
        const live = arr.filter(w => this._isAlive(w));
        if (live.length !== arr.length) {
            for (const w of arr)
                if (!this._isAlive(w))
                    w.disconnectObject(this);
            arr.splice(0, arr.length, ...live);
        }
        if (arr.length === 0) {
            this._batches.delete(monitor);
            return;
        }

        const ws = global.workspace_manager.get_active_workspace();
        const wa = ws.get_work_area_for_monitor(monitor);
        const n = arr.length;
        const cols = this._settings.get_string('orientation') !== 'rows';

        for (let i = 0; i < n; i++) {
            const win = arr[i];
            if (win.maximizedHorizontally || win.maximizedVertically)
                win.unmaximize(Meta.MaximizeFlags.BOTH);

            let x, y, w, h;
            if (cols) {
                const a = wa.x + Math.round((wa.width * i) / n);
                const b = wa.x + Math.round((wa.width * (i + 1)) / n);
                x = a; y = wa.y; w = b - a; h = wa.height;
            } else {
                const a = wa.y + Math.round((wa.height * i) / n);
                const b = wa.y + Math.round((wa.height * (i + 1)) / n);
                x = wa.x; y = a; w = wa.width; h = b - a;
            }
            // userOp = false: programmatic, must not be read as a user grab.
            win.move_resize_frame(false, x, y, w, h);
        }
    }

    _retileAll() {
        for (const monitor of [...this._batches.keys()])
            this._tile(monitor);
    }

    // ----- helpers -----------------------------------------------------------

    _isAlive(win) {
        // Still a managed, on-screen window (has a compositor actor).
        return !!(win && win.get_compositor_private());
    }

    _isTerminal(win) {
        if (!win || win.get_window_type() !== Meta.WindowType.NORMAL)
            return false;
        const needle = this._settings.get_string('terminal-wm-class').toLowerCase();
        if (!needle)
            return true;
        const cls = (win.get_wm_class() || '').toLowerCase();
        const inst = (win.get_wm_class_instance?.() || '').toLowerCase();
        return cls.includes(needle) || inst.includes(needle);
    }
}
