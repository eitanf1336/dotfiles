// Claude Idle Shutdown: adds items to the system Power Off submenu that power
// off (or suspend) the machine once no Claude agent/chat is actively running.
//
// It shells out to ~/bin/claude-shut-launch, which opens ~/bin/await-claude-shut
// in a terminal window so the wait is visible and cancellable (Ctrl+C, or just
// close the window), and falls back to running it headless if no terminal will
// open. All of the terminal handling lives in that script on purpose: script
// fixes take effect on the next click, extension.js fixes need a logout.
//
// Never spawn the terminal from here again. `terminator -x <cmd>` hands the
// command line to an already-running terminator over DBus, which joins the -x
// array into one string and re-splits it, so the arguments were silently lost
// and "Suspend when Claude's done" powered off instead. See the launcher.

import GLib from 'gi://GLib';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const LAUNCHER = '/home/eitan/bin/claude-shut-launch';

// Each entry becomes one action in the Power Off submenu.
const ACTIONS = [
    {label: "Off when Claude's done",     action: 'poweroff'},
    {label: "Suspend when Claude's done", action: 'suspend'},
];

export default class ClaudeIdleShutdownExtension extends Extension {
    enable() {
        // Version marker: extension.js is cached by the shell's module loader,
        // so this is how you prove a reload actually re-read the file.
        console.log('claude-idle-shutdown: enabled (launcher v2)');
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
        for (const {label, action} of ACTIONS) {
            const item = menu.addAction(label, () => {
                Main.panel.closeQuickSettings();
                this._launch(action);
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

    _launch(action) {
        // One argv element per argument, no shell in between, so nothing can
        // re-split them. The launcher logs the click itself, so even a total
        // failure past this point leaves a trace in the waiter's log.
        try {
            GLib.spawn_async(null, [LAUNCHER, action], null,
                GLib.SpawnFlags.DEFAULT, null);
        } catch (e) {
            logError(e, 'claude-idle-shutdown: failed to launch the waiter');
            Main.notifyError("Couldn't arm the Claude shutdown",
                `${LAUNCHER} would not start: ${e.message}`);
        }
    }
}
