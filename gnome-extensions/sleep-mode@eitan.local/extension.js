// Sleep Mode: a "Sleeping" toggle in the quick settings panel, next to the
// power button, for when you go to bed. It is a machine-wide switch rather than
// any one app's setting, and tools opt in by checking it.
//
// The state is a marker file rather than a gsetting so a shell script can test
// it with [ -e ] and no dconf round-trip. The `sleeping` command owns that file;
// this watches it, so flipping it from a terminal moves the toggle, and vice
// versa.

import GObject from 'gi://GObject';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {QuickToggle, SystemIndicator}
    from 'resource:///org/gnome/shell/ui/quickSettings.js';

const STATE_DIR = GLib.build_filenamev(
    [GLib.get_user_state_dir(), 'sleep-mode']);
const STATE_FILE = GLib.build_filenamev([STATE_DIR, 'sleeping']);
const ICON = 'weather-clear-night-symbolic';

const SleepToggle = GObject.registerClass(
class SleepToggle extends QuickToggle {
    constructor() {
        super({
            title: 'Sleeping',
            iconName: ICON,
            toggleMode: true,
        });
    }
});

const SleepIndicator = GObject.registerClass(
class SleepIndicator extends SystemIndicator {
    constructor() {
        super();

        // Only shown while sleeping, as a reminder that things are muted.
        this._icon = this._addIndicator();
        this._icon.iconName = ICON;

        this.toggle = new SleepToggle();
        this.quickSettingsItems.push(this.toggle);
    }
});

export default class SleepModeExtension extends Extension {
    enable() {
        this._writing = false;
        this._indicator = new SleepIndicator();
        this._toggle = this._indicator.toggle;

        this._toggle.connect('notify::checked', () => {
            if (!this._writing)
                this._write(this._toggle.checked);
            this._render();
        });

        // monitor_file() needs the directory to exist to report creates.
        GLib.mkdir_with_parents(STATE_DIR, 0o755);
        try {
            this._monitor = Gio.File.new_for_path(STATE_FILE)
                .monitor_file(Gio.FileMonitorFlags.NONE, null);
            this._monitor.connect('changed', () => this._sync());
        } catch (e) {
            logError(e, 'sleep-mode: could not watch the sleeping file');
        }

        this._sync();
        Main.panel.statusArea.quickSettings.addExternalIndicator(this._indicator);
    }

    disable() {
        this._monitor?.cancel();
        this._monitor = null;
        for (const item of this._indicator?.quickSettingsItems ?? [])
            item.destroy();
        this._indicator?.destroy();
        this._indicator = null;
        this._toggle = null;
    }

    // Adopt whatever the file says, without writing it straight back out.
    _sync() {
        const sleeping = Gio.File.new_for_path(STATE_FILE).query_exists(null);
        this._writing = true;
        this._toggle.checked = sleeping;
        this._writing = false;
        this._render();
    }

    _render() {
        const sleeping = this._toggle.checked;
        this._toggle.subtitle = sleeping ? 'shhh… quiet hours' : null;
        this._indicator._icon.visible = sleeping;
    }

    _write(sleeping) {
        const file = Gio.File.new_for_path(STATE_FILE);
        try {
            if (sleeping) {
                GLib.mkdir_with_parents(STATE_DIR, 0o755);
                file.replace_contents(new TextEncoder().encode('1\n'), null,
                    false, Gio.FileCreateFlags.REPLACE_DESTINATION, null);
            } else {
                file.delete(null);
            }
        } catch (e) {
            // Already gone is the state we wanted anyway.
            if (!e.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.NOT_FOUND))
                logError(e, 'sleep-mode: could not update the sleeping file');
        }
    }
}
