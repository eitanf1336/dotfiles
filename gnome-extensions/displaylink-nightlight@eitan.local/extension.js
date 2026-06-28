import St from 'gi://St';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import Clutter from 'gi://Clutter';
import Cogl from 'gi://Cogl';
import GObject from 'gi://GObject';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {Slider} from 'resource:///org/gnome/shell/ui/slider.js';

// Cogl blend string for a true multiply: result = SRC_COLOR * DST_COLOR.
// Scales each channel of the existing pixel, so blacks stay black and only the
// colour temperature shifts (same as real Night Light).
const MULTIPLY_BLEND = 'RGBA = ADD(SRC_COLOR*(DST_COLOR), DST_COLOR*(ZERO))';

// One full-monitor actor that applies the warm multiply tint and a black dim.
// It paints nothing during OFF-SCREEN captures (screenshots, window
// thumbnails), so the tint/brightness never end up baked into a screenshot.
const OverlayActor = GObject.registerClass(
class OverlayActor extends Clutter.Actor {
    _init(props) {
        super._init(props);
        this._mr = 1; this._mg = 1; this._mb = 1;       // multiply tint colour
        this._fr = 1; this._fg = 1; this._fb = 1; this._fa = 0; // alpha fallback
        this._tintOn = false;
        this._dimAlpha = 0;
        this._useMultiply = true;
    }

    setState(mr, mg, mb, fr, fg, fb, fa, tintOn, dimAlpha) {
        this._mr = mr; this._mg = mg; this._mb = mb;
        this._fr = fr; this._fg = fg; this._fb = fb; this._fa = fa;
        this._tintOn = tintOn;
        this._dimAlpha = dimAlpha;
        this.queue_redraw();
    }

    vfunc_paint_node(node, paintContext) {
        // Skip when painting to an off-screen buffer (no stage view) — this is
        // how screenshots/thumbnails are captured. Guard so that if the method
        // is unavailable we simply paint as normal rather than break.
        try {
            if (typeof paintContext.get_stage_view === 'function' &&
                !paintContext.get_stage_view())
                return;
        } catch (e) {}

        const [w, h] = this.get_size();
        if (w <= 0 || h <= 0)
            return;

        const box = new Clutter.ActorBox();
        box.set_origin(0, 0);
        box.set_size(w, h);

        // --- Warm tint (multiply) ---
        if (this._tintOn) {
            if (this._useMultiply) {
                try {
                    const fb = paintContext.get_framebuffer();
                    const ctx = fb.get_context();
                    const pipeline = new Cogl.Pipeline(ctx);
                    pipeline.set_color4f(this._mr, this._mg, this._mb, 1.0);
                    pipeline.set_blend(MULTIPLY_BLEND);
                    const pnode = Clutter.PipelineNode.new(pipeline);
                    pnode.add_rectangle(box);
                    node.add_child(pnode);
                } catch (e) {
                    logError(e, 'DisplayLink Night Light: multiply unavailable, using alpha fallback');
                    this._useMultiply = false;
                }
            }
            if (!this._useMultiply) {
                try {
                    const color = new Cogl.Color();
                    color.init_from_4f(this._fr, this._fg, this._fb, this._fa);
                    const cnode = Clutter.ColorNode.new(color);
                    cnode.add_rectangle(box);
                    node.add_child(cnode);
                } catch (e) {
                    logError(e, 'DisplayLink Night Light: fallback tint failed');
                }
            }
        }

        // --- Brightness dim (black, alpha = clean multiply-darken) ---
        if (this._dimAlpha > 0.001) {
            try {
                const color = new Cogl.Color();
                color.init_from_4f(0, 0, 0, this._dimAlpha);
                const cnode = Clutter.ColorNode.new(color);
                cnode.add_rectangle(box);
                node.add_child(cnode);
            } catch (e) {
                logError(e, 'DisplayLink Night Light: dim failed');
            }
        }
    }
});

const MAX_INTENSITY = 1.0;

export default class DisplayLinkNightLight extends Extension {
    enable() {
        this._settings = this.getSettings();
        this._overlays = [];
        this._signalIds = [];

        this._monitorsChangedId =
            Main.layoutManager.connect('monitors-changed', () => this._rebuild());

        for (const key of ['active', 'intensity', 'tint-color', 'brightness']) {
            this._signalIds.push(
                this._settings.connect(`changed::${key}`, () => this._updateStyle()));
        }
        this._signalIds.push(
            this._settings.connect('changed::all-monitors', () => this._rebuild()));
        this._signalIds.push(
            this._settings.connect('changed::active', () => {
                if (this._toggle)
                    this._toggle.setToggleState(this._settings.get_boolean('active'));
            }));
        this._signalIds.push(
            this._settings.connect('changed::intensity', () => {
                if (!this._slider)
                    return;
                const v = this._settings.get_double('intensity') / MAX_INTENSITY;
                if (Math.abs(v - this._slider.value) > 0.001)
                    this._slider.value = v;
            }));

        this._addIndicator();
        this._rebuild();

        Main.wm.addKeybinding(
            'toggle-shortcut',
            this._settings,
            Meta.KeyBindingFlags.NONE,
            Shell.ActionMode.ALL,
            () => this._settings.set_boolean('active', !this._settings.get_boolean('active')));
    }

    disable() {
        Main.wm.removeKeybinding('toggle-shortcut');

        if (this._monitorsChangedId) {
            Main.layoutManager.disconnect(this._monitorsChangedId);
            this._monitorsChangedId = null;
        }
        if (this._settings)
            this._signalIds.forEach(id => this._settings.disconnect(id));
        this._signalIds = [];

        this._destroyOverlays();

        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
            this._toggle = null;
            this._slider = null;
        }
        this._settings = null;
    }

    _destroyOverlays() {
        this._overlays.forEach(o => o.destroy());
        this._overlays = [];
    }

    _rebuild() {
        this._destroyOverlays();

        const allMonitors = this._settings.get_boolean('all-monitors');
        const primaryIndex = Main.layoutManager.primaryIndex;
        const uiGroup = Main.layoutManager.uiGroup;

        Main.layoutManager.monitors.forEach((monitor, index) => {
            if (!allMonitors && index === primaryIndex)
                return;

            const overlay = new OverlayActor({reactive: false});
            overlay.set_position(monitor.x, monitor.y);
            overlay.set_size(monitor.width, monitor.height);
            uiGroup.add_child(overlay);
            uiGroup.set_child_above_sibling(overlay, null);
            this._overlays.push(overlay);
        });

        this._updateStyle();
    }

    _updateStyle() {
        const active = this._settings.get_boolean('active');
        const intensity = this._settings.get_double('intensity');
        const brightness = this._settings.get_double('brightness');
        const {r, g, b} = this._parseHex(this._settings.get_string('tint-color'));

        const tr = r / 255, tg = g / 255, tb = b / 255;
        const mr = 1 - intensity * (1 - tr);
        const mg = 1 - intensity * (1 - tg);
        const mb = 1 - intensity * (1 - tb);
        const fa = Math.min(intensity * 0.85, 0.85);

        const tintOn = active && intensity > 0;
        const dimAlpha = Math.max(0, Math.min(0.9, 1 - brightness));

        this._overlays.forEach(o => {
            o.setState(mr, mg, mb, tr, tg, tb, fa, tintOn, dimAlpha);
            o.visible = tintOn || dimAlpha > 0.001;
        });
    }

    _parseHex(hex) {
        const m = /^#?([0-9a-fA-F]{6})$/.exec((hex || '').trim());
        if (!m)
            return {r: 255, g: 178, b: 122};
        const n = parseInt(m[1], 16);
        return {r: (n >> 16) & 0xff, g: (n >> 8) & 0xff, b: n & 0xff};
    }

    _addIndicator() {
        const indicator = new PanelMenu.Button(0.0, this.metadata.name, false);
        indicator.add_child(new St.Icon({
            icon_name: 'night-light-symbolic',
            style_class: 'system-status-icon',
        }));

        const toggle = new PopupMenu.PopupSwitchMenuItem(
            'Warm tint', this._settings.get_boolean('active'));
        toggle.connect('toggled',
            (item, state) => this._settings.set_boolean('active', state));
        indicator.menu.addMenuItem(toggle);
        this._toggle = toggle;

        // Tint strength slider.
        const tintItem = new PopupMenu.PopupBaseMenuItem({activate: false});
        tintItem.add_child(new St.Icon({
            icon_name: 'night-light-symbolic',
            style_class: 'popup-menu-icon',
        }));
        const tintSlider = new Slider(this._settings.get_double('intensity') / MAX_INTENSITY);
        tintSlider.x_expand = true;
        tintSlider.connect('notify::value',
            () => this._settings.set_double('intensity', tintSlider.value * MAX_INTENSITY));
        tintItem.add_child(tintSlider);
        indicator.menu.addMenuItem(tintItem);
        this._slider = tintSlider;

        // Brightness slider (0.1 .. 1.0).
        const dimItem = new PopupMenu.PopupBaseMenuItem({activate: false});
        dimItem.add_child(new St.Icon({
            icon_name: 'display-brightness-symbolic',
            style_class: 'popup-menu-icon',
        }));
        const dimSlider = new Slider((this._settings.get_double('brightness') - 0.1) / 0.9);
        dimSlider.x_expand = true;
        dimSlider.connect('notify::value',
            () => this._settings.set_double('brightness', 0.1 + dimSlider.value * 0.9));
        dimItem.add_child(dimSlider);
        indicator.menu.addMenuItem(dimItem);
        this._signalIds.push(this._settings.connect('changed::brightness', () => {
            const v = (this._settings.get_double('brightness') - 0.1) / 0.9;
            if (Math.abs(v - dimSlider.value) > 0.001)
                dimSlider.value = v;
        }));

        indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const prefsItem = new PopupMenu.PopupMenuItem('Settings…');
        prefsItem.connect('activate', () => this.openPreferences());
        indicator.menu.addMenuItem(prefsItem);

        Main.panel.addToStatusArea(this.uuid, indicator);
        this._indicator = indicator;
    }
}
