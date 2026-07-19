import Gio from 'gi://Gio';
import Meta from 'gi://Meta';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

// Expose "show me the desktop" over D-Bus, for the money + surf panels.
//
// Those widgets sit on the wallpaper below every other window, so the only way
// to reveal them is to clear the desktop first. Nothing outside the shell can do
// that any more: Mutter still lists _NET_SHOWING_DESKTOP in _NET_SUPPORTED but
// ignores the client message, and an XWayland client cannot minimise native
// Wayland windows even in principle. Shell code can, so `panels` calls Show() /
// Restore() here on Ctrl+Shift+M.
const IFACE = `
<node>
  <interface name="org.gnome.Shell.Extensions.ShowDesktop">
    <method name="Show"/>
    <method name="Restore"/>
    <method name="Toggle">
      <arg type="b" direction="out" name="showing"/>
    </method>
    <property name="Showing" type="b" access="read"/>
  </interface>
</node>`;

const PATH = '/org/gnome/Shell/Extensions/ShowDesktop';

export default class ShowDesktopExtension extends Extension {
    enable() {
        this._hidden = [];      // only windows WE minimised, in stacking order
        this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        this._dbus.export(Gio.DBus.session, PATH);

        // A window we hid can be closed while the desktop is exposed; forget it
        // so Restore never touches a dead window.
        this._destroyId = global.window_manager.connect('destroy', (_wm, actor) => {
            this._hidden = this._hidden.filter(w => w !== actor.meta_window);
        });
    }

    disable() {
        // Extensions are disabled on lock/logout. Leaving the session with every
        // window minimised and no way back would be a trap, so always undo.
        this.Restore();

        if (this._destroyId) {
            global.window_manager.disconnect(this._destroyId);
            this._destroyId = null;
        }
        this._dbus?.unexport();
        this._dbus = null;
        this._hidden = [];
    }

    get Showing() {
        return this._hidden.length > 0;
    }

    // Skip the panels themselves and the desktop-icons window: they set
    // skip-taskbar, and they are the whole point of exposing the desktop.
    // Only touch windows on the primary monitor: the panels live there, so
    // there is no reason to minimise whatever the user has open on the other
    // screens. `primary` is the primary monitor index (see Show()).
    _shouldHide(w, primary) {
        return !w.minimized && !w.skip_taskbar && w.can_minimize() &&
               w.get_window_type() === Meta.WindowType.NORMAL &&
               w.get_monitor() === primary;
    }

    Show() {
        if (this.Showing)
            return;

        const primary = global.display.get_primary_monitor();
        const ws = global.workspace_manager.get_active_workspace();
        const windows = ws.list_windows().filter(w => this._shouldHide(w, primary));

        // Bottom-to-top, so Restore can replay the same order and hand back the
        // stack the user had rather than a reshuffled one.
        for (const w of global.display.sort_windows_by_stacking(windows)) {
            this._hidden.push(w);
            w.minimize();
        }
    }

    Restore() {
        const hidden = this._hidden;
        this._hidden = [];

        // Same bottom-to-top order: the window that was on top is unminimised
        // last and so lands back on top, with focus.
        for (const w of hidden) {
            try {
                w.unminimize();
            } catch (_e) {
                // window died while the desktop was exposed; nothing to restore
            }
        }
    }

    Toggle() {
        if (this.Showing)
            this.Restore();
        else
            this.Show();
        return this.Showing;
    }
}
