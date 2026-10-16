// Adds "Edit" next to "Show in Files" on GNOME's screenshot notification.
// GNOME 50's _storeScreenshot() is module-private, so we wrap
// MessageTray.Notification.prototype.addAction and react only on the
// screenshot notification's "Show in Files" action. The file is written
// synchronously before the notification exists, so the newest PNG is it.
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Gettext from 'gettext';
import * as MessageTray from 'resource:///org/gnome/shell/ui/messageTray.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const shellGettext = s => Gettext.domain('gnome-shell').gettext(s);
const APP = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'screenshot-markup']);

function newestScreenshot() {
    const pics = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) ??
        GLib.build_filenamev([GLib.get_home_dir(), 'Pictures']);
    const dir = Gio.File.new_for_path(GLib.build_filenamev([pics, shellGettext('Screenshots')]));
    let best = null, bestT = -1;
    const en = dir.enumerate_children('standard::name,time::modified', 0, null);
    let info;
    while ((info = en.next_file(null))) {
        const n = info.get_name();
        if (!n.toLowerCase().endsWith('.png') || n.includes('-marked')) continue;
        const t = info.get_attribute_uint64('time::modified');
        if (t > bestT) { bestT = t; best = dir.get_child(n); }
    }
    en.close(null);
    return best;
}

export default class ScreenshotMarkupExtension extends Extension {
    enable() {
        this._orig = MessageTray.Notification.prototype.addAction;
        const orig = this._orig;
        const showInFiles = shellGettext('Show in Files');
        const captureTitle = shellGettext('Screen Capture');
        const shotTitle = shellGettext('Screenshot captured');
        MessageTray.Notification.prototype.addAction = function (label, callback) {
            const ret = orig.call(this, label, callback);
            try {
                // GNOME 50 bug: Source.iconName getter reads this.gicon but the
                // setter writes this.icon, so source.iconName is always undefined.
                // Match on several independent signals instead.
                const src = this.source;
                let iconStr = '';
                try { iconStr = src?.icon?.to_string?.() ?? ''; } catch (e) {}
                const isCapture = iconStr.includes('screenshooter') ||
                    src?.title === captureTitle || src?.title === 'Screen Capture' ||
                    this.title === shotTitle || this.title === 'Screenshot captured';
                const isShow = label === showInFiles || label === 'Show in Files';
                if (isShow && isCapture && !this._ssmEdit) {
                    this._ssmEdit = true;
                    const file = newestScreenshot();
                    if (file) {
                        this.isTransient = false;   // keep it in the message tray
                        orig.call(this, 'Edit', () => {
                            try {
                                Gio.Subprocess.new([APP, file.get_path()], Gio.SubprocessFlags.NONE);
                            } catch (e) {
                                logError(e, 'screenshot-markup: launch failed');
                            }
                        });
                    }
                }
            } catch (e) {
                logError(e, 'screenshot-markup: could not add Edit action');
            }
            return ret;
        };
    }

    disable() {
        try {
            if (this._orig) MessageTray.Notification.prototype.addAction = this._orig;
        } catch (e) {
            logError(e, 'screenshot-markup: restore failed');
        }
        this._orig = null;
    }
}
