// Claude Idle Shutdown: adds items to the system Power Off submenu that power
// off (or suspend) the machine once no Claude agent/chat is actively running.
//
// It shells out to ~/bin/await-claude-shut inside a terminator window so the
// wait is visible and cancellable (Ctrl+C, or just close the window).

import GLib from 'gi://GLib';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const WAITER = '/home/eitan/bin/await-claude-shut';
const TERMINAL = '/usr/bin/terminator';

// Each entry becomes one action in the Power Off submenu.
const ACTIONS = [
    {label: "Off when Claude's done",     action: 'poweroff',
     title: "Shut down when Claude's done"},
    {label: "Suspend when Claude's done", action: 'suspend',
     title: "Suspend when Claude's done"},
];

export default class ClaudeIdleShutdownExtension extends Extension {
    enable() {
        this._items = [];
        this._menu = null;
        this._timeout = 0;
        this._tries = 0;
        // The quick-settings indicators are set up asynchronously, so the
        // Power Off submenu may not exist yet at enable() time, so retry briefly.
        if (!this._install())
            this._scheduleRetry();
    }

    disable() {
        if (this._timeout) {
            GLib.Source.remove(this._timeout);
            this._timeout = 0;
        }
        for (const item of this._items ?? [])
            item?.destroy();
        this._items = [];
        this._menu = null;
    }

    _install() {
        // Path (GNOME 47–50): the ShutdownItem's menu is exposed as
        // quickSettings._system._systemItem.menu, the Power Off submenu with
        // Suspend / Restart / Power Off / Log Out; addAction() appends to it.
        const menu = Main.panel.statusArea.quickSettings
            ?._system?._systemItem?.menu;
        if (!menu)
            return false;
        this._menu = menu;
        for (const {label, action, title} of ACTIONS) {
            const item = menu.addAction(label, () => {
                Main.panel.closeQuickSettings();
                this._launch(action, title);
            });
            this._items.push(item);
        }
        return true;
    }

    _scheduleRetry() {
        this._timeout = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 500, () => {
            if (this._install() || ++this._tries > 20) {
                this._timeout = 0;
                if (!this._menu)
                    logError(new Error(
                        'claude-idle-shutdown: Power Off submenu never appeared'));
                return GLib.SOURCE_REMOVE;
            }
            return GLib.SOURCE_CONTINUE;
        });
    }

    _launch(action, title) {
        // Keep the window open if the wait is cancelled (non-zero exit); on a
        // real power-off/suspend the machine is going down so the tail is moot.
        const shellCmd =
            `${GLib.shell_quote(WAITER)} --action ${action} --grace 90; ec=$?; ` +
            '[ "$ec" = 0 ] || { echo; ' +
            'read -n1 -rsp "[cancelled, press any key to close]"; echo; }';
        const argv = [TERMINAL, '-T', title,
                      '-x', 'bash', '-lc', shellCmd];
        try {
            GLib.spawn_async(null, argv, null,
                GLib.SpawnFlags.DEFAULT, null);
        } catch (e) {
            logError(e, 'claude-idle-shutdown: failed to launch the waiter');
        }
    }
}
