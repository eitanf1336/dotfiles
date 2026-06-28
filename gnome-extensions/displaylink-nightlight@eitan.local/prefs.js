import Adw from 'gi://Adw';
import Gtk from 'gi://Gtk';
import Gdk from 'gi://Gdk';
import Gio from 'gi://Gio';

import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

export default class DisplayLinkNightLightPrefs extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();
        const page = new Adw.PreferencesPage();
        window.add(page);

        const group = new Adw.PreferencesGroup({title: 'Warm Tint'});
        page.add(group);

        // Enabled
        const activeRow = new Adw.SwitchRow({
            title: 'Enabled',
            subtitle: 'Show the warm overlay',
        });
        group.add(activeRow);
        settings.bind('active', activeRow, 'active', Gio.SettingsBindFlags.DEFAULT);

        // Intensity
        const intensityRow = new Adw.SpinRow({
            title: 'Tint strength',
            subtitle: 'Warm multiply strength (0 = off, 1 = full warm)',
            adjustment: new Gtk.Adjustment({
                lower: 0,
                upper: 1,
                step_increment: 0.05,
                page_increment: 0.1,
            }),
            digits: 2,
        });
        group.add(intensityRow);
        settings.bind('intensity', intensityRow, 'value', Gio.SettingsBindFlags.DEFAULT);

        // Brightness
        const brightnessRow = new Adw.SpinRow({
            title: 'Screen brightness',
            subtitle: 'Software dim (1 = native, 0.1 = darkest). Cannot exceed the panel’s own max.',
            adjustment: new Gtk.Adjustment({
                lower: 0.1,
                upper: 1,
                step_increment: 0.05,
                page_increment: 0.1,
            }),
            digits: 2,
        });
        group.add(brightnessRow);
        settings.bind('brightness', brightnessRow, 'value', Gio.SettingsBindFlags.DEFAULT);

        // Tint colour
        const colorRow = new Adw.ActionRow({
            title: 'Tint color',
            subtitle: 'Lower (deeper orange) = warmer',
        });
        const colorBtn = new Gtk.ColorDialogButton({
            dialog: new Gtk.ColorDialog({with_alpha: false}),
            valign: Gtk.Align.CENTER,
        });
        const rgba = new Gdk.RGBA();
        rgba.parse(settings.get_string('tint-color'));
        colorBtn.set_rgba(rgba);
        colorBtn.connect('notify::rgba', () => {
            const c = colorBtn.get_rgba();
            const hex = '#' + [c.red, c.green, c.blue]
                .map(v => Math.round(v * 255).toString(16).padStart(2, '0'))
                .join('');
            settings.set_string('tint-color', hex);
        });
        colorRow.add_suffix(colorBtn);
        colorRow.activatable_widget = colorBtn;
        group.add(colorRow);

        // Monitors
        const monGroup = new Adw.PreferencesGroup({title: 'Monitors'});
        page.add(monGroup);
        const allRow = new Adw.SwitchRow({
            title: 'Tint all monitors',
            subtitle: 'Off = skip the primary monitor (use hardware Night Light there instead)',
        });
        monGroup.add(allRow);
        settings.bind('all-monitors', allRow, 'active', Gio.SettingsBindFlags.DEFAULT);

        // Tips
        const tips = new Adw.PreferencesGroup({title: 'Tips'});
        page.add(tips);
        tips.add(new Adw.ActionRow({
            title: 'Toggle shortcut',
            subtitle: 'Super + Shift + N',
        }));
        tips.add(new Adw.ActionRow({
            title: 'Quick adjust',
            subtitle: 'Click the panel icon, or scroll over it to change strength',
        }));
    }
}
