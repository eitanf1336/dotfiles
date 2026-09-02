import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

// Session restore. `claude-session` (see ~/bin/claude-session) needs two
// things from us that nothing else can provide: which columns were on which
// monitor when the session ended, and a way to put a terminal back INTO a
// column rather than as a stray window. The layout is dumped on disable(),
// which is what a logout triggers; SpawnTiled is the way back in.
const IFACE = `
<node>
  <interface name="eitan.TerminalTiler">
    <method name="SpawnTiled">
      <arg type="u" direction="in" name="monitor"/>
      <arg type="s" direction="in" name="command"/>
    </method>
    <method name="GetLayout">
      <arg type="s" direction="out" name="json"/>
    </method>
  </interface>
</node>`;

const KEY = 'tile-new-terminal';
const MIN_KEY = 'minimize-terminal-group';
const MOVE_LEFT_KEY = 'move-terminal-left';
const MOVE_RIGHT_KEY = 'move-terminal-right';
const FOCUS_LEFT_KEY = 'focus-terminal-left';
const FOCUS_RIGHT_KEY = 'focus-terminal-right';
const MAX_KEY = 'maximize-terminal';
const UNMAX_KEY = 'unmaximize-terminal';

// Grab-op flag that Mutter ORs into the op for unconstrained moves.
const GRAB_OP_WINDOW_FLAG_UNCONSTRAINED = 1024;

// Frames within this many px of their target slot are treated as already
// placed, so _tile skips a redundant resize (see _tile). Comfortably above a
// terminal snapping its frame to whole character cells, well below any real
// column-width change.
const SLOT_EPS = 8;

// A grab that leaves the frame within this many px of its slot was a click or
// a nudge, not a deliberate move, so the window stays in its group.
const EJECT_MIN = 40;

export default class TerminalTilerExtension extends Extension {
    enable() {
        this._settings = this.getSettings();

        // Session restore hook (see the IFACE comment above). Exported on the
        // shell's own bus name, so `gdbus call --dest org.gnome.Shell
        // --object-path /eitan/TerminalTiler` reaches it. Wrapped in a try so a
        // bus that refuses the export can never stop the tiler itself loading.
        try {
            this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
            this._dbus.export(Gio.DBus.session, '/eitan/TerminalTiler');
        } catch (e) {
            logError(e, 'Terminal Tiler: could not export the restore interface');
            this._dbus = null;
        }

        // monitorIndex -> ordered array of Meta.Window (one batch per monitor).
        this._batches = new Map();
        // monitorIndex -> the one Meta.Window currently maximised over its
        // batch (fills the work area, peers hidden behind it). Absent unless
        // that monitor's group is in the temporary maximised state.
        this._maxed = new Map();
        // monitors waiting for a freshly-spawned terminal window to appear.
        this._pending = [];
        // Re-entrancy guard while we propagate minimize/restore across a batch.
        this._syncing = false;
        // Window currently being moved/resized by the user (between grab-op
        // begin and end) — its size changes are a deliberate drag, not an
        // external tiler we should fight, so the size-changed watcher skips it.
        this._grabWin = null;
        // Pending delayed re-flows (GLib timeout ids), see _scheduleRetile.
        this._retileIds = new Set();
        // True while _regroup is re-flowing, so _tile does not recurse into it.
        this._regrouping = false;

        Main.wm.addKeybinding(
            KEY,
            this._settings,
            Meta.KeyBindingFlags.IGNORE_AUTOREPEAT,
            Shell.ActionMode.NORMAL,
            this._onActivate.bind(this)
        );

        // Minimise the focused monitor's whole batch at once.
        Main.wm.addKeybinding(
            MIN_KEY,
            this._settings,
            Meta.KeyBindingFlags.IGNORE_AUTOREPEAT,
            Shell.ActionMode.NORMAL,
            this._onMinimizeGroup.bind(this)
        );

        // Reorder the focused terminal within its group (swap with the
        // neighbour to its left/right) and re-flow.
        Main.wm.addKeybinding(
            MOVE_LEFT_KEY,
            this._settings,
            Meta.KeyBindingFlags.NONE,
            Shell.ActionMode.NORMAL,
            () => this._onMove(-1)
        );
        Main.wm.addKeybinding(
            MOVE_RIGHT_KEY,
            this._settings,
            Meta.KeyBindingFlags.NONE,
            Shell.ActionMode.NORMAL,
            () => this._onMove(1)
        );

        // Walk keyboard focus along the group without moving any window.
        Main.wm.addKeybinding(
            FOCUS_LEFT_KEY,
            this._settings,
            Meta.KeyBindingFlags.NONE,
            Shell.ActionMode.NORMAL,
            () => this._onFocusMove(-1)
        );
        Main.wm.addKeybinding(
            FOCUS_RIGHT_KEY,
            this._settings,
            Meta.KeyBindingFlags.NONE,
            Shell.ActionMode.NORMAL,
            () => this._onFocusMove(1)
        );

        // Maximise the focused terminal over its group / restore the division.
        Main.wm.addKeybinding(
            MAX_KEY,
            this._settings,
            Meta.KeyBindingFlags.IGNORE_AUTOREPEAT,
            Shell.ActionMode.NORMAL,
            this._onMaximize.bind(this)
        );
        Main.wm.addKeybinding(
            UNMAX_KEY,
            this._settings,
            Meta.KeyBindingFlags.IGNORE_AUTOREPEAT,
            Shell.ActionMode.NORMAL,
            this._onUnmaximize.bind(this)
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
        // so this only ever fires for genuine user actions.) We also track the
        // window under an active grab so the size-changed watcher below leaves
        // a deliberate drag-resize alone (grab-op-end handles those by ejecting).
        global.display.connectObject(
            'grab-op-begin',
            (_disp, win) => { this._grabWin = win; },
            'grab-op-end',
            (_disp, win) => this._onGrabOpEnd(win),
            this
        );

        // A batch member gained focus → bring the rest of its group along
        // (restore any minimised peers, raise them all). Activating a window
        // always fires this, so it reliably covers "restore one → restore all"
        // even on restore paths that skip the WM unminimize signal.
        global.display.connectObject(
            'notify::focus-window',
            () => this._onFocusChanged(),
            this
        );

        // A batch member was minimised/restored → do the same to the rest, so
        // the group hides and returns as a unit. The window-manager emits these
        // for every animation; Meta.Window's read-only `minimized` property does
        // NOT fire `notify::`, so we must listen here rather than on the window.
        global.window_manager.connectObject(
            'minimize', (_wm, actor) => this._onWmMinimize(actor, true),
            'unminimize', (_wm, actor) => this._onWmMinimize(actor, false),
            this
        );

        // Re-flow when monitors are added/removed so stale geometry is fixed.
        // One pass is not enough: on a hotplug the dock is destroyed and
        // rebuilt asynchronously and Mutter recomputes work areas on an idle,
        // so re-flowing right now measures the *old* screen. Repeat a beat
        // later, and again once everything has settled.
        Main.layoutManager.connectObject(
            'monitors-changed',
            () => this._scheduleRetile([0, 800, 2500]),
            this
        );

        // Struts changed: a dock appeared, vanished, changed monitor or size.
        // Without this the columns keep whatever work area they were tiled
        // against, which is how the first column ends up buried under the
        // dock and stays there. Our own move_resize_frame never changes a
        // strut, so this cannot feed back into itself.
        global.display.connectObject(
            'workareas-changed',
            () => this._scheduleRetile([250]),
            this
        );
    }

    disable() {
        Main.wm.removeKeybinding(KEY);
        Main.wm.removeKeybinding(MIN_KEY);
        Main.wm.removeKeybinding(MOVE_LEFT_KEY);
        Main.wm.removeKeybinding(MOVE_RIGHT_KEY);
        Main.wm.removeKeybinding(FOCUS_LEFT_KEY);
        Main.wm.removeKeybinding(FOCUS_RIGHT_KEY);
        Main.wm.removeKeybinding(MAX_KEY);
        Main.wm.removeKeybinding(UNMAX_KEY);
        global.display.disconnectObject(this);
        global.window_manager.disconnectObject(this);
        Main.layoutManager.disconnectObject(this);

        // Drop our handlers from every tracked window.
        for (const arr of this._batches.values())
            for (const win of arr)
                win.disconnectObject(this);

        if (this._retileIds) {
            for (const id of this._retileIds)
                GLib.Source.remove(id);
            this._retileIds = null;
        }

        // A logout runs disable(), which is the last moment the column layout
        // still exists. Write it out so `claude-session restore` can put the
        // same chats back on the same monitors at the next login.
        this._saveLayout();
        if (this._dbus) {
            try {
                this._dbus.unexport();
            } catch (e) {
                // Shutting down anyway; nothing useful to do about it.
            }
            this._dbus = null;
        }

        this._batches = null;
        this._pending = null;
        this._settings = null;
        this._grabWin = null;
        this._maxed = null;
        this._regrouping = false;
    }

    // ----- core action -------------------------------------------------------

    _onActivate() {
        const focus = global.display.focus_window;
        const monitor = focus
            ? focus.get_monitor()
            : global.display.get_current_monitor();

        // A stray terminal is focused and not yet managed → absorb it.
        // (Explicit "add this terminal" gesture wins over summoning.)
        if (this._isTerminal(focus) && this._monitorOf(focus) === null) {
            this._maxed.delete(monitor);
            this._add(monitor, focus);
            this._tile(monitor);
            return;
        }

        // A batch lives on this monitor but isn't the focused window → summon
        // the whole group to the front and focus it (over everything else).
        const arr = this._batches.get(monitor);
        const groupFocused = this._monitorOf(focus) === monitor;
        if (arr && arr.length && !groupFocused) {
            this._raiseGroup(monitor);
            return;
        }

        // Otherwise spawn a fresh terminal onto the focused monitor. When a
        // group window is already focused this adds another column and re-tiles.
        this._spawnInto(monitor);
    }

    // Bring every window in a monitor's batch to the front, restoring any that
    // are minimised, and give keyboard focus to the first column.
    _raiseGroup(monitor) {
        const arr = this._batches.get(monitor);
        if (!arr || !arr.length)
            return;
        const time = global.get_current_time();
        this._syncing = true; // restoring here; don't let the cascade fight us.
        for (const win of arr) {
            if (!this._isAlive(win))
                continue;
            if (win.minimized)
                win.unminimize();
            win.raise();
        }
        this._syncing = false;
        // Re-flow so the group returns in its proper shape: full-screen if it
        // is still maximised, equal columns/rows otherwise. Then raise the
        // right window to the top (the maximised one, else the first column).
        this._tile(monitor);
        const maxed = this._maxed.get(monitor);
        const front = (maxed && this._isAlive(maxed))
            ? maxed
            : arr.find(w => this._isAlive(w));
        if (front)
            front.activate(time);
    }

    // A window just gained focus. If it belongs to a batch, bring its peers
    // along: restore any that are minimised and raise them all to the front, so
    // the group travels together (clicking/activating one terminal — including
    // restoring it from minimised — lifts the whole column set). Raising does
    // not steal focus back, and tiled members don't overlap, so their relative
    // z-order among themselves doesn't matter. Guarded so our own
    // unminimize()/raise() calls here don't re-enter.
    _onFocusChanged() {
        if (this._syncing)
            return;
        const win = global.display.focus_window;
        const monitor = this._monitorOf(win);
        if (monitor === null)
            return;
        const arr = this._batches.get(monitor);
        if (!arr)
            return;
        // Maximised: keep the one full-screen terminal on top and leave the
        // covered peers hidden, rather than raising the whole group (which
        // would pop the peers out from behind it).
        const maxed = this._maxed.get(monitor);
        if (maxed) {
            if (this._isAlive(maxed)) {
                this._syncing = true;
                if (maxed.minimized)
                    maxed.unminimize();
                maxed.raise();
                this._syncing = false;
            }
            return;
        }
        this._syncing = true;
        for (const w of arr) {
            if (w === win || !this._isAlive(w))
                continue;
            if (w.minimized)
                w.unminimize();
            w.raise();
        }
        this._syncing = false;
    }

    // Toggle the batch on the focused window's monitor (or, if a non-batch
    // window is focused, whichever monitor it sits on): if any member is still
    // open, minimise the whole group; if they are all minimised, bring them back.
    _onMinimizeGroup() {
        const focus = global.display.focus_window;
        let monitor = this._monitorOf(focus);
        if (monitor === null) {
            const m = focus
                ? focus.get_monitor()
                : global.display.get_current_monitor();
            if (this._batches.has(m))
                monitor = m;
        }
        if (monitor === null)
            return;
        const arr = this._batches.get(monitor);
        if (!arr || !arr.length)
            return;

        const anyOpen = arr.some(w => this._isAlive(w) && !w.minimized);
        if (!anyOpen) {
            this._raiseGroup(monitor);
            return;
        }
        // Minimising ends any maximise: the group returns divided next time.
        this._maxed.delete(monitor);
        this._syncing = true;
        for (const win of arr)
            if (this._isAlive(win) && !win.minimized)
                win.minimize();
        this._syncing = false;
    }

    // Move the focused terminal one slot within its group: delta -1 swaps it
    // with the previous member (left column / row above), +1 with the next
    // (right column / row below), then re-flows so positions update. No-op if
    // the focused window isn't in a batch or is already at the relevant edge.
    _onMove(delta) {
        const focus = global.display.focus_window;
        let monitor = this._monitorOf(focus);
        // A managed terminal can fall out of its batch: a stray title-bar drag
        // ejects it (by design), and Tiling Assistant — kept enabled for every
        // other app — can snatch a dragged terminal into a half-tile. Once it's
        // out, reordering silently no-ops, so the key feels like it "stopped
        // working". Re-absorb a focused terminal back into its monitor's
        // existing batch so Super+Left/Right springs back to life on the next
        // press instead of going dead.
        if (monitor === null && this._isTerminal(focus)) {
            const m = focus.get_monitor();
            if (this._batches.has(m)) {
                this._add(m, focus);
                this._tile(m);
                monitor = m;
            }
        }
        if (monitor === null) {
            // Focus isn't a managed terminal in a batch. Fall back to a plain
            // left/right half-tile so Super+Left/Right keeps working for every
            // other window now that the tiler — not Tiling Assistant — owns
            // these keys (mirrors the maximize/unmaximize fallbacks so no app
            // loses the shortcut). No batch is touched, so there's no re-flow.
            this._halfTile(focus, delta);
            return;
        }
        const arr = this._batches.get(monitor);
        if (!arr)
            return;
        const i = arr.indexOf(focus);
        const j = i + delta;
        if (i < 0 || j < 0 || j >= arr.length)
            return;
        [arr[i], arr[j]] = [arr[j], arr[i]];
        // Reordering means the user wants the columns, so drop any maximise.
        this._maxed.delete(monitor);
        this._tile(monitor);
    }

    // Snap a non-managed window to the left (delta<0) or right (delta>0) half
    // of its monitor's work area — the plain edge-tile Tiling Assistant used to
    // do on Super+Left/Right, reimplemented here so those keys keep tiling
    // ordinary windows now that the terminal tiler owns them. The window isn't
    // in a batch (no size-changed watcher), so this can't start a re-flow loop.
    _halfTile(win, delta) {
        if (!win || win.get_window_type() !== Meta.WindowType.NORMAL)
            return;
        const wa = this._workArea(win.get_monitor());
        if (win.maximizedHorizontally || win.maximizedVertically)
            win.unmaximize(Meta.MaximizeFlags.BOTH);
        const half = Math.round(wa.width / 2);
        const x = delta < 0 ? wa.x : wa.x + (wa.width - half);
        win.move_resize_frame(false, x, wa.y, half, wa.height);
    }

    // Walk keyboard focus one slot along the group WITHOUT moving any window:
    // delta -1 focuses the previous member (left column / row above), +1 the
    // next. The target is activate()d, so the very next keystroke goes into
    // that terminal — handy for hopping between two Claude sessions side by
    // side. At either end of the group, hop to the batch on the adjacent
    // monitor if one exists, so the keys keep walking across screens.
    _onFocusMove(delta) {
        const focus = global.display.focus_window;
        let monitor = this._monitorOf(focus);
        // Same re-absorb as _onMove: a terminal ejected by a stray drag would
        // otherwise make the key silently dead until it is re-added.
        if (monitor === null && this._isTerminal(focus)) {
            const m = focus.get_monitor();
            if (this._batches.has(m)) {
                this._add(m, focus);
                this._tile(m);
                monitor = m;
            }
        }
        if (monitor === null) {
            // Not one of our terminals — keep the accelerator's old meaning
            // (these arrows were Mutter's switch-to-workspace-left/right until
            // the tiler took them) so no other window loses the shortcut.
            this._switchWorkspace(delta);
            return;
        }
        const arr = this._batches.get(monitor);
        if (!arr)
            return;
        const live = arr.filter(w => this._isAlive(w));
        const i = live.indexOf(focus);
        if (i < 0)
            return;
        const j = i + delta;
        const target = (j >= 0 && j < live.length)
            ? live[j]
            : this._edgeTerminal(monitor, delta);
        if (!target || target === focus)
            return;
        this._focusTerminal(target);
    }

    // Give `win` keyboard focus, restoring/raising it first so it is really on
    // screen and really typable. If its monitor's group is in the maximised
    // (one full-screen terminal) state, move the maximise onto `win` too —
    // otherwise focus would land on a peer hidden behind the maximised one.
    _focusTerminal(win) {
        const monitor = this._monitorOf(win);
        if (monitor !== null && this._maxed.has(monitor)) {
            this._maxed.set(monitor, win);
            this._tile(monitor);
        }
        this._syncing = true;
        if (win.minimized)
            win.unminimize();
        win.raise();
        this._syncing = false;
        // Not guarded: the focus change should still pull the rest of the
        // group along, exactly as a click on that terminal would.
        win.activate(global.get_current_time());
    }

    // First/last terminal of the nearest batch on a monitor to the left
    // (delta<0) or right (delta>0) of `fromMonitor`, or null if there is none.
    // Monitors are ordered by the centre of their geometry, so this follows the
    // physical screen layout rather than the arbitrary monitor indices.
    _edgeTerminal(fromMonitor, delta) {
        const mons = Main.layoutManager.monitors;
        const from = mons[fromMonitor];
        if (!from)
            return null;
        const fromMid = from.x + from.width / 2;
        let best = null, bestDist = Infinity;
        for (const [idx, arr] of this._batches) {
            if (idx === fromMonitor)
                continue;
            const m = mons[idx];
            if (!m)
                continue;
            const d = (m.x + m.width / 2) - fromMid;
            // Wrong side of the current monitor (or stacked exactly on it).
            if (delta < 0 ? d >= 0 : d <= 0)
                continue;
            if (Math.abs(d) < bestDist) {
                bestDist = Math.abs(d);
                best = arr;
            }
        }
        if (!best)
            return null;
        const live = best.filter(w => this._isAlive(w));
        if (!live.length)
            return null;
        // Enter the neighbouring group from the side we arrived on.
        return delta < 0 ? live[live.length - 1] : live[0];
    }

    // Plain workspace switch, the stock meaning of these arrows before the
    // tiler claimed them (see _onFocusMove's fallback).
    _switchWorkspace(delta) {
        const wm = global.workspace_manager;
        const idx = wm.get_active_workspace_index() + delta;
        if (idx < 0 || idx >= wm.get_n_workspaces())
            return;
        wm.get_workspace_by_index(idx).activate(global.get_current_time());
    }

    // Maximise the focused terminal over the rest of its group: it grows to
    // fill the monitor's whole work area and covers its peers, so one terminal
    // is temporarily full-screen without leaving the batch. The peers stay
    // alive (never minimised) behind it; _unmaximize (or minimising the group)
    // brings the column division back. Re-absorbs a focused terminal that fell
    // out of its batch first, mirroring _onMove, so the key keeps working.
    _onMaximize() {
        const focus = global.display.focus_window;
        let monitor = this._monitorOf(focus);
        if (monitor === null && this._isTerminal(focus)) {
            const m = focus.get_monitor();
            if (this._batches.has(m)) {
                this._add(m, focus);
                this._tile(m);
                monitor = m;
            }
        }
        const arr = monitor === null ? null : this._batches.get(monitor);
        if (!arr || !arr.includes(focus)) {
            // Not one of our tiled terminals — behave like a plain maximize so
            // Super+Up still works for every other window (Tiling Assistant no
            // longer owns it).
            if (focus && !focus.maximizedHorizontally && !focus.maximizedVertically)
                focus.maximize(Meta.MaximizeFlags.BOTH);
            return;
        }
        this._maxed.set(monitor, focus);
        this._tile(monitor);
    }

    // Undo _onMaximize: forget the maximised window on the focused window's
    // monitor (or, if a non-batch window is focused, whichever monitor is
    // currently maximised) and re-flow that batch back into columns/rows.
    _onUnmaximize() {
        const focus = global.display.focus_window;
        let monitor = this._monitorOf(focus);
        if (monitor === null) {
            const m = focus
                ? focus.get_monitor()
                : global.display.get_current_monitor();
            if (this._maxed.has(m))
                monitor = m;
        }
        if (monitor === null || !this._maxed.has(monitor)) {
            // Not a maximised batch — behave like a plain unmaximize so
            // Super+Down still restores every other window.
            if (focus && (focus.maximizedHorizontally || focus.maximizedVertically))
                focus.unmaximize(Meta.MaximizeFlags.BOTH);
            return;
        }
        this._maxed.delete(monitor);
        this._tile(monitor);
    }

    // A window was minimised (minimized=true) or restored (false) via the WM.
    // If it belongs to a batch, mirror the change across the rest so the group
    // minimises and restores as a unit. Our own minimize()/unminimize() calls
    // re-enter through this signal, hence the `_syncing` guard.
    _onWmMinimize(actor, minimized) {
        if (this._syncing)
            return;
        const win = actor?.meta_window;
        const monitor = this._monitorOf(win);
        if (monitor === null)
            return;
        const arr = this._batches.get(monitor);
        if (!arr)
            return;
        // Minimising the group ends any maximise, so it comes back divided.
        if (minimized)
            this._maxed.delete(monitor);
        this._syncing = true;
        for (const w of arr) {
            if (w === win || !this._isAlive(w))
                continue;
            if (minimized) {
                if (!w.minimized)
                    w.minimize();
            } else if (w.minimized) {
                w.unminimize();
            }
        }
        this._syncing = false;
        // On restore, re-flow so a group that was maximised before it went
        // away returns to its column division rather than staying full-screen.
        if (!minimized)
            this._tile(monitor);
    }

    _spawnInto(monitor) {
        // A new column means we are back to a division, not a maximise.
        this._maxed.delete(monitor);
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
            // Mutter may well have opened it on another screen. Move it first,
            // so it really lives on the monitor whose column it is taking.
            // Otherwise _tile sees a stray and hands it to the other screen.
            if (monitor < Main.layoutManager.monitors.length &&
                win.get_monitor() !== monitor)
                win.move_to_monitor(monitor);
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
        this._grabWin = null;
        const monitor = this._monitorOf(win);
        if (monitor === null)
            return;
        // A plain click on the title bar, or a nudge of a few pixels, ends as
        // a grab op too. Ejecting on those leaves a stray terminal parked on
        // top of the columns that re-flow underneath it, which is exactly
        // what "the windows are on top of each other" looks like. So only a
        // deliberate move counts; anything smaller snaps back onto its slot.
        const arr = this._batches.get(monitor);
        const live = arr ? arr.filter(w => this._isAlive(w)) : [];
        const i = live.indexOf(win);
        if (i >= 0) {
            const cols = this._settings.get_string('orientation') !== 'rows';
            const s = this._slotRect(this._workArea(monitor), i, live.length, cols);
            const r = win.get_frame_rect();
            const nudged =
                Math.abs(r.x - s.x) <= EJECT_MIN &&
                Math.abs(r.y - s.y) <= EJECT_MIN &&
                Math.abs(r.width - s.w) <= EJECT_MIN &&
                Math.abs(r.height - s.h) <= EJECT_MIN;
            if (nudged) {
                this._tile(monitor);
                return;
            }
        }
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
        // Forget the window when it closes, then re-flow its monitor. Also
        // watch its size: if another tiler (e.g. the Tiling Assistant
        // extension's Super+Up / Super+Left bindings) maximises or tiles it out
        // of its column, snap it straight back.
        win.connectObject(
            'unmanaging', () => {
                // Look the monitor up again: a re-home (see _regroup) may have
                // moved this window to another screen's batch since we added it.
                const m = this._monitorOf(win);
                if (m === null)
                    return;
                this._remove(win, m);
                this._tile(m);
            },
            'size-changed', () => this._onSizeChanged(win),
            this);
    }

    _remove(win, monitor) {
        const arr = this._batches.get(monitor);
        if (!arr)
            return;
        const i = arr.indexOf(win);
        if (i >= 0)
            arr.splice(i, 1);
        win.disconnectObject(this);
        // If the maximised terminal is the one leaving (ejected or closed),
        // forget the maximise so the rest re-flow into columns.
        if (this._maxed.get(monitor) === win)
            this._maxed.delete(monitor);
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

        // Windows that now live on a different screen (a hotplug or a resume
        // moved them, and Mutter renumbered the monitors under us) must not be
        // laid out here: this batch and that screen's own batch would both
        // divide the same monitor and the columns would land on top of each
        // other. Hand everything to _regroup, which re-homes and re-flows.
        if (!this._regrouping) {
            const nMon = Main.layoutManager.monitors.length;
            const strayed = arr.some(w => {
                const m = w.get_monitor();
                return m >= 0 && m < nMon && m !== monitor;
            });
            if (monitor >= nMon || strayed) {
                this._regroup();
                return;
            }
        }

        const wa = this._workArea(monitor);
        const n = arr.length;
        const cols = this._settings.get_string('orientation') !== 'rows';

        // Maximised: one terminal fills the whole work area and its peers stay
        // parked in their old column slots behind it. We only size the
        // maximised window and raise it over the rest; _slotRect / the per-slot
        // loop below are skipped entirely until the maximise is cleared.
        const maxed = this._maxed.get(monitor);
        if (maxed && this._isAlive(maxed) && arr.includes(maxed)) {
            const r = maxed.get_frame_rect();
            const onFull =
                !maxed.maximizedHorizontally && !maxed.maximizedVertically &&
                Math.abs(r.x - wa.x) <= SLOT_EPS &&
                Math.abs(r.y - wa.y) <= SLOT_EPS &&
                Math.abs(r.width - wa.width) <= SLOT_EPS &&
                Math.abs(r.height - wa.height) <= SLOT_EPS;
            if (!onFull) {
                if (maxed.maximizedHorizontally || maxed.maximizedVertically)
                    maxed.unmaximize();
                maxed.move_resize_frame(false, wa.x, wa.y, wa.width, wa.height);
            }
            maxed.raise();
            return;
        }
        // Stale/cleared maximise: fall through to the normal column division.
        if (maxed)
            this._maxed.delete(monitor);

        for (let i = 0; i < n; i++) {
            const win = arr[i];
            const s = this._slotRect(wa, i, n, cols);

            // Skip windows already on their slot. A redundant move_resize_frame
            // still emits size-changed, and with Tiling Assistant also poking
            // these windows (kept on for every other app) plus terminals running
            // focus-reporting TUIs, those needless events churn the group and
            // make a terminal spew escape sequences. Only touch a frame that
            // genuinely needs to move; SLOT_EPS absorbs char-cell rounding.
            const r = win.get_frame_rect();
            const onSlot =
                !win.maximizedHorizontally && !win.maximizedVertically &&
                Math.abs(r.x - s.x) <= SLOT_EPS &&
                Math.abs(r.y - s.y) <= SLOT_EPS &&
                Math.abs(r.width - s.w) <= SLOT_EPS &&
                Math.abs(r.height - s.h) <= SLOT_EPS;
            if (onSlot)
                continue;

            if (win.maximizedHorizontally || win.maximizedVertically)
                win.unmaximize();

            // userOp = false: programmatic, must not be read as a user grab.
            win.move_resize_frame(false, s.x, s.y, s.w, s.h);
        }
    }

    // Work area for a monitor, minus any dock mutter failed to carve out.
    // Mutter only honours a strut whose actor touches an outer edge of the
    // combined screen, so with side-by-side monitors a fixed Dash-to-Dock on
    // an inner monitor (multi-monitor docks) overlaps the reported work area
    // instead of shrinking it, and tiles slide underneath it. Re-do the
    // subtraction here for every visible strut-requesting chrome actor that
    // still overlaps the area; honoured struts (leftmost dock, top bar) lie
    // outside the reported area already, so they skip via the overlap test.
    _workArea(monitor) {
        const ws = global.workspace_manager.get_active_workspace();
        const wa = ws.get_work_area_for_monitor(monitor);
        let x = wa.x, y = wa.y;
        let right = wa.x + wa.width, bottom = wa.y + wa.height;
        for (const data of Main.layoutManager._trackedActors ?? []) {
            const actor = data.actor;
            if (!data.affectsStruts || !actor || !actor.visible)
                continue;
            const [ax, ay] = actor.get_transformed_position().map(Math.round);
            const [aw, ah] = actor.get_transformed_size().map(Math.round);
            const ax2 = ax + aw, ay2 = ay + ah;
            if (ax >= right || ax2 <= x || ay >= bottom || ay2 <= y)
                continue;
            // Trim from whichever edge of the area the actor hugs: a vertical
            // dock eats width, a horizontal panel eats height. An actor
            // floating mid-area matches no case and is left alone.
            if (ax <= x && ax2 < right)
                x = ax2;
            else if (ax2 >= right && ax > x)
                right = ax;
            else if (ay <= y && ay2 < bottom)
                y = ay2;
            else if (ay2 >= bottom && ay > y)
                bottom = ay;
        }
        if (right - x < 100 || bottom - y < 100)
            return wa;
        return {x, y, width: right - x, height: bottom - y};
    }

    // Geometry of the i-th of n equal slices of work area `wa` (vertical
    // columns when `cols`, horizontal rows otherwise). Shared by _tile (to
    // place windows) and _onSizeChanged (to tell when one has wandered off).
    _slotRect(wa, i, n, cols) {
        if (cols) {
            const a = wa.x + Math.round((wa.width * i) / n);
            const b = wa.x + Math.round((wa.width * (i + 1)) / n);
            return {x: a, y: wa.y, w: b - a, h: wa.height};
        }
        const a = wa.y + Math.round((wa.height * i) / n);
        const b = wa.y + Math.round((wa.height * (i + 1)) / n);
        return {x: wa.x, y: a, w: wa.width, h: b - a};
    }

    // A managed terminal's size changed. If something other than us maximised
    // or tiled it off its column slot — typically another extension grabbing
    // Super+Up / Super+Left while the terminal is focused — pull it back in.
    // Ignored cases that must NOT trigger a re-flow:
    //   * a user drag-resize (handled by grab-op-end, which ejects instead);
    //   * our own move_resize_frame, which lands on-slot and un-maximised, so
    //     the deviation check below is false and this is a no-op (no loop).
    // The tolerance absorbs a terminal snapping its frame to whole character
    // cells; real tiles/maximises deviate by hundreds of pixels.
    _onSizeChanged(win) {
        if (this._syncing || win === this._grabWin || !this._isAlive(win))
            return;
        const monitor = this._monitorOf(win);
        if (monitor === null)
            return;
        // The maximised terminal is meant to fill the work area — its size
        // deviating from a column slot is intentional, not a stray tile.
        if (this._maxed.get(monitor) === win)
            return;
        const arr = this._batches.get(monitor);
        if (!arr)
            return;
        const live = arr.filter(w => this._isAlive(w));
        const i = live.indexOf(win);
        if (i < 0)
            return;

        const wa = this._workArea(monitor);
        const cols = this._settings.get_string('orientation') !== 'rows';
        const s = this._slotRect(wa, i, live.length, cols);
        const r = win.get_frame_rect();
        const TOL = 80;
        const offSlot =
            Math.abs(r.x - s.x) > TOL || Math.abs(r.y - s.y) > TOL ||
            Math.abs(r.width - s.w) > TOL || Math.abs(r.height - s.h) > TOL;

        if (!offSlot && !win.maximizedHorizontally && !win.maximizedVertically)
            return;

        // Drop any Tiling-Assistant bookkeeping so it stops treating this
        // terminal as one of its tiles, then re-flow the column.
        delete win.isTiled;
        delete win.tiledRect;
        delete win.untiledRect;
        this._tile(monitor);
    }

    _retileAll() {
        this._regroup();
    }

    // Re-home every managed terminal into the batch of the monitor it is
    // ACTUALLY on, then re-flow every batch.
    //
    // Batches are keyed by monitor index, and those indices are not stable:
    // unplugging a screen (or one waking up late after a suspend) makes Mutter
    // move the windows onto a surviving monitor and renumber the rest, while
    // the batch keeps its old key. Two batches then divide one screen and the
    // columns sit on top of each other. Rebuilding from where the windows
    // really are fixes that, and re-orders each batch to match what is on
    // screen so the columns keep their left-to-right identity.
    _regroup() {
        if (!this._batches || this._regrouping)
            return;

        const nMon = Main.layoutManager.monitors.length;
        if (nMon === 0)
            return;
        const cols = this._settings.get_string('orientation') !== 'rows';
        const rehomed = new Map();

        for (const [key, arr] of this._batches) {
            for (const win of arr) {
                if (!this._isAlive(win)) {
                    win.disconnectObject(this);
                    continue;
                }
                let m = win.get_monitor();
                // Off every screen for a moment (mid-unmap, or the monitor it
                // was on has just left): keep it in the group rather than lose
                // it, on the nearest still-existing screen. Tiling it there
                // gives it a real monitor again.
                if (m < 0 || m >= nMon)
                    m = Math.max(0, Math.min(key, nMon - 1));
                let dst = rehomed.get(m);
                if (!dst)
                    rehomed.set(m, dst = []);
                if (!dst.includes(win))
                    dst.push(win);
            }
        }

        for (const arr of rehomed.values()) {
            arr.sort((a, b) => cols
                ? a.get_frame_rect().x - b.get_frame_rect().x
                : a.get_frame_rect().y - b.get_frame_rect().y);
        }

        // A maximise follows its window to whatever screen it ended up on.
        const maxed = new Map();
        for (const win of this._maxed.values()) {
            if (!this._isAlive(win))
                continue;
            const m = win.get_monitor();
            if (rehomed.get(m)?.includes(win))
                maxed.set(m, win);
        }
        this._maxed.clear();
        for (const [m, win] of maxed)
            this._maxed.set(m, win);

        this._batches.clear();
        for (const [m, arr] of rehomed)
            this._batches.set(m, arr);

        this._regrouping = true;
        try {
            for (const m of [...this._batches.keys()])
                this._tile(m);
        } finally {
            this._regrouping = false;
        }
    }

    // Re-flow every batch after each delay in `delays` (ms). Several passes,
    // because the chrome that defines the usable area (dock, panel) and
    // Mutter's own work-area recalculation both land asynchronously, some
    // frames after the event that triggered them, so measuring only once
    // means measuring the screen as it was.
    _scheduleRetile(delays) {
        if (!this._retileIds)
            return;
        for (const ms of delays) {
            const id = GLib.timeout_add(
                GLib.PRIORITY_DEFAULT, Math.max(ms, 1), () => {
                    this._retileIds?.delete(id);
                    this._regroup();
                    return GLib.SOURCE_REMOVE;
                });
            this._retileIds.add(id);
        }
    }

    // ----- session restore ---------------------------------------------------

    // D-Bus: open `command` as a new column on `monitor`. Same path Super+Return
    // takes — push the monitor onto _pending, spawn, and let _onWindowCreated
    // claim the window when it maps. Used by `claude-session restore` at login.
    SpawnTiled(monitor, command) {
        if (!this._pending)
            return;
        const n = global.display.get_n_monitors();
        const idx = Math.max(0, Math.min(monitor, n - 1));
        this._maxed.delete(idx);
        this._pending.push(idx);
        try {
            const [ok, argv] = GLib.shell_parse_argv(command);
            if (ok) {
                GLib.spawn_async(null, argv, null,
                    GLib.SpawnFlags.SEARCH_PATH, null);
                return;
            }
        } catch (e) {
            logError(e, `Terminal Tiler: SpawnTiled could not launch "${command}"`);
        }
        this._pending.pop();   // nothing was spawned; don't strand the slot
    }

    // D-Bus: the current column layout, same shape as the file below.
    GetLayout() {
        return JSON.stringify(this._layout());
    }

    _layout() {
        const monitors = {};
        if (this._batches) {
            for (const [idx, arr] of this._batches) {
                const titles = [];
                for (const win of arr) {
                    if (this._isAlive(win))
                        titles.push(win.get_title() || '');
                }
                if (titles.length)
                    monitors[String(idx)] = titles;
            }
        }
        return {saved: Date.now() / 1000, monitors};
    }

    // Persist the layout to ~/.claude/chats-session/tiler-layout.json. Called
    // from disable(), i.e. on logout, which is exactly when it is needed and
    // also the last moment the window list is still real.
    _saveLayout() {
        try {
            const dir = GLib.build_filenamev(
                [GLib.get_home_dir(), '.claude', 'chats-session']);
            GLib.mkdir_with_parents(dir, 0o755);
            const path = GLib.build_filenamev([dir, 'tiler-layout.json']);
            GLib.file_set_contents(path, JSON.stringify(this._layout(), null, 2));
        } catch (e) {
            logError(e, 'Terminal Tiler: could not save the column layout');
        }
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
