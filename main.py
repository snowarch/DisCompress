#!/usr/bin/env python3
import os
import subprocess
import math

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, GObject, GLib, Gdk  # type: ignore


FFMPEG_PRESETS = [
    "ultrafast",
    "superfast",
    "veryfast",
    "faster",
    "fast",
    "medium",
    "slow",
    "slower",
    "veryslow",
]


def run_bash(cmd: str) -> subprocess.Popen:
    return subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        executable="/bin/bash",
        bufsize=1,
    )


def ffprobe_duration(path: str) -> float:
    cmd = (
        "ffprobe -v error -show_entries format=duration "
        "-of default=noprint_wrappers=1:nokey=1 '%s'" % path
    )
    proc = run_bash(cmd)
    out, _ = proc.communicate()
    try:
        return float(out.strip())
    except Exception:
        return 0.0


class VideoCompressorWindow(Gtk.Window):
    def __init__(self) -> None:
        super().__init__(title="DisCompress")
        self.set_default_size(900, 520)

        self.process: subprocess.Popen | None = None
        self.duration: float = 0.0

        self.input_path: str | None = None
        self.output_path: str | None = None
        self.last_output_path: str | None = None

        self._build_ui()
        self._apply_css()

        self.connect("destroy", Gtk.main_quit)

    # UI -----------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer.set_border_width(8)
        self.add(outer)

        header = Gtk.HeaderBar(title="DisCompress")
        header.set_subtitle("Discord-ready video compressor")
        header.set_show_close_button(True)
        self.set_titlebar(header)

        self.btn_compress = Gtk.Button(label="Compress")
        self.btn_compress.connect("clicked", self.on_compress_clicked)
        header.pack_end(self.btn_compress)

        self.btn_cancel = Gtk.Button(label="Cancel")
        self.btn_cancel.connect("clicked", self.on_cancel_clicked)
        self.btn_cancel.set_sensitive(False)
        header.pack_end(self.btn_cancel)

        # Top: file area -------------------------------------------------
        file_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        outer.pack_start(file_box, False, False, 0)

        # Drag & drop area
        self.drop_area = Gtk.EventBox()
        self.drop_area.set_visible_window(True)
        self.drop_area.set_above_child(False)
        frame = Gtk.Frame()
        frame.set_shadow_type(Gtk.ShadowType.IN)
        self.drop_area.add(frame)

        drop_label = Gtk.Label(
            label="Drop your Discord clip here or use the 'Choose file' button",
        )
        drop_label.set_margin_top(18)
        drop_label.set_margin_bottom(18)
        frame.add(drop_label)

        file_box.pack_start(self.drop_area, False, False, 0)

        # DnD setup
        target = Gtk.TargetEntry.new("text/uri-list", 0, 0)
        self.drop_area.drag_dest_set(
            Gtk.DestDefaults.ALL,
            [target],
            Gdk.DragAction.COPY,
        )
        self.drop_area.connect("drag-data-received", self.on_drag_data_received)

        # Path row
        path_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        file_box.pack_start(path_row, False, False, 0)

        self.entry_input = Gtk.Entry()
        self.entry_input.set_placeholder_text("Input video path")
        path_row.pack_start(self.entry_input, True, True, 0)

        btn_choose = Gtk.Button(label="Choose file")
        btn_choose.connect("clicked", self.on_choose_clicked)
        path_row.pack_start(btn_choose, False, False, 0)

        # Info line ------------------------------------------------------
        info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        outer.pack_start(info_box, False, False, 0)

        self.lbl_duration = Gtk.Label(label="Duration: --")
        self.lbl_duration.set_xalign(0.0)
        info_box.pack_start(self.lbl_duration, True, True, 0)

        self.lbl_estimate = Gtk.Label(label="Estimate: --")
        self.lbl_estimate.set_xalign(1.0)
        info_box.pack_start(self.lbl_estimate, True, True, 0)

        # Middle: settings + preview ------------------------------------
        paned = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        outer.pack_start(paned, True, True, 0)

        # Left: settings panel
        settings_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        settings_box.set_border_width(6)
        paned.add1(settings_box)

        # Target size
        size_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        settings_box.pack_start(size_row, False, False, 0)

        lbl_size = Gtk.Label(label="Target size (MB):")
        lbl_size.set_xalign(0.0)
        size_row.pack_start(lbl_size, True, True, 0)

        adj_size = Gtk.Adjustment(10.0, 1.0, 50_000.0, 1.0, 50.0, 0.0)
        self.spin_size = Gtk.SpinButton()
        self.spin_size.set_adjustment(adj_size)
        self.spin_size.set_digits(1)
        self.spin_size.set_value(10.0)
        self.spin_size.connect("value-changed", self.on_params_changed)
        size_row.pack_start(self.spin_size, False, False, 0)

        self.lbl_profile_hint = Gtk.Label(label="")
        self.lbl_profile_hint.set_xalign(0.0)
        self.lbl_profile_hint.get_style_context().add_class("dim-label")
        settings_box.pack_start(self.lbl_profile_hint, False, False, 0)

        preset_size_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        settings_box.pack_start(preset_size_row, False, False, 0)

        lbl_preset_size = Gtk.Label(label="Discord presets:")
        lbl_preset_size.set_xalign(0.0)
        preset_size_row.pack_start(lbl_preset_size, True, True, 0)

        btn_8 = Gtk.Button(label="8 MB (Free)")
        btn_8.connect("clicked", self.on_preset_size_clicked, 8.0)
        preset_size_row.pack_start(btn_8, False, False, 0)

        btn_25 = Gtk.Button(label="25 MB (Nitro)")
        btn_25.connect("clicked", self.on_preset_size_clicked, 25.0)
        preset_size_row.pack_start(btn_25, False, False, 0)

        # Audio bitrate
        audio_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        settings_box.pack_start(audio_row, False, False, 0)

        lbl_audio = Gtk.Label(label="Audio (kbps):")
        lbl_audio.set_xalign(0.0)
        audio_row.pack_start(lbl_audio, True, True, 0)

        adj_audio = Gtk.Adjustment(128.0, 32.0, 512.0, 8.0, 32.0, 0.0)
        self.spin_audio = Gtk.SpinButton()
        self.spin_audio.set_adjustment(adj_audio)
        self.spin_audio.set_digits(0)
        self.spin_audio.set_value(128.0)
        self.spin_audio.connect("value-changed", self.on_params_changed)
        audio_row.pack_start(self.spin_audio, False, False, 0)

        # Preset selector + slider
        preset_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        settings_box.pack_start(preset_row, False, False, 0)

        lbl_preset = Gtk.Label(label="Preset x264:")
        lbl_preset.set_xalign(0.0)
        preset_row.pack_start(lbl_preset, True, True, 0)

        self.combo_preset = Gtk.ComboBoxText()
        for p in FFMPEG_PRESETS:
            self.combo_preset.append_text(p)
        self.combo_preset.set_active(FFMPEG_PRESETS.index("veryslow"))
        preset_row.pack_start(self.combo_preset, False, False, 0)

        # CRF/quality visual slider (visual only)
        qual_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        settings_box.pack_start(qual_box, False, False, 0)

        lbl_qual = Gtk.Label(label="Speed / quality balance:")
        lbl_qual.set_xalign(0.0)
        qual_box.pack_start(lbl_qual, False, False, 0)

        self.scale_qual = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 8, 1)
        self.scale_qual.set_draw_value(False)
        self.scale_qual.set_value(8)
        self.scale_qual.connect("value-changed", self.on_quality_slider_changed)
        qual_box.pack_start(self.scale_qual, False, False, 0)

        hints_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        qual_box.pack_start(hints_box, False, False, 0)
        hints_box.pack_start(Gtk.Label(label="Fast"), False, False, 0)
        hints_box.pack_end(Gtk.Label(label="Best quality"), False, False, 0)

        # Output path
        out_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        settings_box.pack_start(out_row, False, False, 4)

        lbl_out = Gtk.Label(label="Output:")
        lbl_out.set_xalign(0.0)
        out_row.pack_start(lbl_out, False, False, 0)

        self.entry_output = Gtk.Entry()
        self.entry_output.set_placeholder_text("Output file path")
        out_row.pack_start(self.entry_output, True, True, 0)

        btn_out = Gtk.Button(label="Cambiar")
        btn_out.connect("clicked", self.on_output_clicked)
        out_row.pack_start(btn_out, False, False, 0)

        # Status label
        self.lbl_status = Gtk.Label(label="Ready.")
        self.lbl_status.set_xalign(0.0)
        settings_box.pack_end(self.lbl_status, False, False, 0)

        # Right: log + progress ------------------------------------------
        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        right_box.set_border_width(6)
        paned.add2(right_box)

        self.progress = Gtk.ProgressBar()
        right_box.pack_start(self.progress, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        right_box.pack_start(scrolled, True, True, 0)

        self.text_log = Gtk.TextView()
        self.text_log.set_editable(False)
        self.text_log.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        scrolled.add(self.text_log)

    def _apply_css(self) -> None:
        css = b"""
        window {
            background-color: #050509;
            color: #f5f5ff;
        }
        headerbar {
            background: #10101a;
            color: #f5f5ff;
        }
        entry, spinbutton, combobox, textview, scale, progressbar {
            background-color: #101019;
            color: #f5f5ff;
        }
        textview text {
            background-color: #050509;
            color: #f5f5ff;
        }
        .drop-area {
            border: 1px dashed #5865f2;
            border-radius: 6px;
        }
        .dim-label {
            color: #8a8ab5;
        }
        """
        provider = Gtk.CssProvider()
        try:
            provider.load_from_data(css)
        except Exception:
            return
        screen = Gdk.Screen.get_default()
        if screen is not None:
            Gtk.StyleContext.add_provider_for_screen(
                screen,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

        # Give style class to drop frame
        ctx = self.drop_area.get_style_context()
        ctx.add_class("drop-area")

    # Events --------------------------------------------------------------
    def on_drag_data_received(self, widget, drag_context, x, y, data, info, time):  # type: ignore[override]
        uris = data.get_uris()
        if not uris:
            return
        uri = uris[0]
        if uri.startswith("file://"):
            path = uri[7:]
        else:
            path = uri
        path = path.strip()
        if os.path.isfile(path):
            self.set_input_file(path)

    def on_choose_clicked(self, button) -> None:  # type: ignore[override]
        dialog = Gtk.FileChooserDialog(
            title="Select video",
            parent=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN,
            Gtk.ResponseType.OK,
        )
        filt = Gtk.FileFilter()
        filt.set_name("Videos")
        filt.add_mime_type("video/*")
        filt.add_pattern("*.mp4")
        filt.add_pattern("*.mkv")
        filt.add_pattern("*.mov")
        filt.add_pattern("*.webm")
        dialog.add_filter(filt)

        resp = dialog.run()
        if resp == Gtk.ResponseType.OK:
            path = dialog.get_filename()
            if path:
                self.set_input_file(path)
        dialog.destroy()

    def on_output_clicked(self, button) -> None:  # type: ignore[override]
        dialog = Gtk.FileChooserDialog(
            title="Output path",
            parent=self,
            action=Gtk.FileChooserAction.SAVE,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            Gtk.STOCK_SAVE,
            Gtk.ResponseType.OK,
        )
        dialog.set_do_overwrite_confirmation(True)

        if self.output_path:
            dialog.set_filename(self.output_path)

        resp = dialog.run()
        if resp == Gtk.ResponseType.OK:
            path = dialog.get_filename()
            if path:
                self.output_path = path
                self.entry_output.set_text(path)
        dialog.destroy()

    def on_params_changed(self, widget) -> None:  # type: ignore[override]
        self.update_estimate()

    def on_quality_slider_changed(self, widget) -> None:  # type: ignore[override]
        idx = int(round(self.scale_qual.get_value()))
        idx = max(0, min(idx, len(FFMPEG_PRESETS) - 1))
        self.combo_preset.set_active(idx)

    def on_preset_size_clicked(self, button, size_mb: float) -> None:
        self.spin_size.set_value(size_mb)
        self.update_estimate()

    # Core logic ----------------------------------------------------------
    def set_input_file(self, path: str) -> None:
        self.input_path = path
        self.entry_input.set_text(path)

        # Proponer salida
        base, ext = os.path.splitext(path)
        self.output_path = base + "_compressed" + (ext or ".mp4")
        self.entry_output.set_text(self.output_path)

        self.append_log(f"\n== Selected file ==\n{path}\n")

        self.lbl_status.set_text("Analyzing duration with ffprobe...")
        self.duration = 0.0

        def worker() -> None:
            dur = ffprobe_duration(path)
            GLib.idle_add(self._on_duration_ready, dur)

        import threading

        threading.Thread(target=worker, daemon=True).start()

    def _on_duration_ready(self, dur: float) -> None:
        self.duration = dur
        if dur > 0:
            self.lbl_duration.set_text(f"Duration: {dur:.1f} s")
            self.lbl_status.set_text("Duration detected.")
        else:
            self.lbl_duration.set_text("Duration: unknown")
            self.lbl_status.set_text("Could not get duration.")
        self.update_estimate()

    def update_estimate(self) -> None:
        if not self.duration or self.duration <= 0:
            self.lbl_estimate.set_text("Estimate: --")
            self.lbl_profile_hint.set_text("")
            return
        size_mb = self.spin_size.get_value()
        audio_k = self.spin_audio.get_value()

        total_bits = size_mb * 1024 * 1024 * 8
        audio_bps = audio_k * 1000
        video_bps = max(total_bits / self.duration - audio_bps, 150_000)
        video_k = video_bps / 1000.0

        approx_size_mb = (video_bps + audio_bps) * self.duration / 8 / (1024 * 1024)

        self.lbl_estimate.set_text(
            f"Video ~{video_k:.0f} kbps, audio {audio_k:.0f} kbps → ~{approx_size_mb:.1f} MB"
        )

        profile = ""
        if size_mb <= 8.0:
            profile = "Profile: Discord Free (<= 8 MB)"
        elif size_mb <= 25.0:
            profile = "Profile: Discord Nitro (<= 25 MB)"
        else:
            profile = "Profile: Custom (may exceed Discord limits)"
        self.lbl_profile_hint.set_text(profile)

    def on_compress_clicked(self, button) -> None:  # type: ignore[override]
        if self.process is not None:
            self.append_log("\n[!] A compression job is already running.\n")
            return

        inp = self.entry_input.get_text().strip()
        outp = self.entry_output.get_text().strip()

        if not inp or not os.path.isfile(inp):
            self.show_error("Select a valid input video.")
            return
        if not outp:
            self.show_error("Provide an output path.")
            return

        size_mb = self.spin_size.get_value()
        audio_k = self.spin_audio.get_value()
        if size_mb <= 0:
            self.show_error("Target size must be greater than 0.")
            return

        # Recalcular bitrates por si la duración se obtuvo tarde
        if not self.duration or self.duration <= 0:
            self.duration = ffprobe_duration(inp)

        if not self.duration or self.duration <= 0:
            self.show_error("Could not get video duration.")
            return

        total_bits = size_mb * 1024 * 1024 * 8
        audio_bps = audio_k * 1000
        video_bps = max(total_bits / self.duration - audio_bps, 150_000)
        video_k = video_bps / 1000.0
        approx_size_mb = (video_bps + audio_bps) * self.duration / 8 / (1024 * 1024)

        self.last_output_path = outp
        preset = self.combo_preset.get_active_text() or "veryslow"

        self.append_log(
            f"\n== Starting ffmpeg ==\n"
            f"Input: {inp}\nOutput: {outp}\n"
            f"Duration: {self.duration:.1f} s\n"
            f"Video: {video_k:.0f} kbps, Audio: {audio_k:.0f} kbps → ~{approx_size_mb:.1f} MB\n"
            f"Preset: {preset}\n\n"
        )

        cmd = (
            f"ffmpeg -y -i '{inp}' -c:v libx264 -preset {preset} "
            f"-b:v {int(video_bps)} -maxrate {int(video_bps)} -bufsize {int(video_bps*2)} "
            f"-c:a aac -b:a {int(audio_bps)} '{outp}'"
        )

        self.append_log(cmd + "\n\n")
        self.lbl_status.set_text("Running ffmpeg...")
        self.progress.set_fraction(0.0)
        self.progress.set_text("")

        self.btn_compress.set_sensitive(False)
        self.btn_cancel.set_sensitive(True)

        self.process = run_bash(cmd)
        if self.process.stdout is not None:
            GLib.io_add_watch(
                self.process.stdout,
                GLib.IO_IN | GLib.IO_HUP,
                self.on_ffmpeg_io,
            )

    def on_ffmpeg_io(self, stream, condition):  # type: ignore[override]
        if condition & GLib.IO_HUP:
            # Fin de stream
            self.finish_process()
            return False
        line = stream.readline()
        if not line:
            self.finish_process()
            return False
        self.append_log(line)
        self.update_progress_from_line(line)
        return True

    def update_progress_from_line(self, line: str) -> None:
        if "time=" not in line:
            return
        try:
            part = line.split("time=")[1].split(" ")[0]
            h, m, s = part.split(":")
            cur = int(h) * 3600 + int(m) * 60 + float(s)
        except Exception:
            return
        if not self.duration or self.duration <= 0:
            return
        frac = max(0.0, min(cur / self.duration, 1.0))
        self.progress.set_fraction(frac)
        self.progress.set_text(f"{int(frac*100)} %")

    def finish_process(self) -> None:
        if self.process is None:
            return
        code = self.process.poll()
        self.process = None

        self.btn_compress.set_sensitive(True)
        self.btn_cancel.set_sensitive(False)

        if code == 0:
            self.progress.set_fraction(1.0)
            self.progress.set_text("100 %")
            if self.last_output_path:
                self.lbl_status.set_text(f"Done: {self.last_output_path}")
            else:
                self.lbl_status.set_text("Done.")
            self.append_log("\n[OK] ffmpeg finished successfully.\n")
            msg = "Compression finished."
            if self.last_output_path:
                msg = (
                    "Compression finished.\n\n"
                    f"Saved to:\n{self.last_output_path}"
                )
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.NONE,
                text="DisCompress",
            )
            dialog.format_secondary_text(msg)
            if self.last_output_path:
                dialog.add_button("Open folder", 1)
                dialog.add_button("Copy path", 2)
            dialog.add_button("Close", Gtk.ResponseType.CLOSE)
            resp = dialog.run()
            if resp == 1 and self.last_output_path:
                folder = os.path.dirname(self.last_output_path)
                if folder:
                    run_bash(f"xdg-open '{folder}'")
            elif resp == 2 and self.last_output_path:
                clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
                clipboard.set_text(self.last_output_path, -1)
            dialog.destroy()
        else:
            self.lbl_status.set_text(f"Error (exit code {code}).")
            self.append_log(f"\n[!] ffmpeg exited with code {code}.\n")

    def on_cancel_clicked(self, button) -> None:  # type: ignore[override]
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            self.append_log("\n[!] Process cancelled by user.\n")
            self.lbl_status.set_text("Cancelled.")

    # Helpers ------------------------------------------------------------
    def append_log(self, text: str) -> None:
        buf = self.text_log.get_buffer()
        end_iter = buf.get_end_iter()
        buf.insert(end_iter, text)
        mark = buf.create_mark(None, buf.get_end_iter(), False)
        self.text_log.scroll_mark_onscreen(mark)

    def show_error(self, msg: str) -> None:
        self.lbl_status.set_text(msg)
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text="Error",
        )
        dialog.format_secondary_text(msg)
        dialog.run()
        dialog.destroy()


def main() -> None:
    win = VideoCompressorWindow()
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
