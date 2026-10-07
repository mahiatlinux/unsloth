# Linux Debian dictation dependency verification

Issue: https://github.com/unslothai/unsloth/issues/11939

Base: e7cc9d5e43. The issue is assigned to the authenticated contributor, mahiatlinux; no PR linked to the issue was found at triage.

## Reproduced failure

Ubuntu 26.04, WebKitGTK 2.52.6, GStreamer 1.28.2. The probe applies Studio's `enable-media-stream` setting and user-media permission handler. It requests the same echo cancellation/noise suppression constraints and the dictation adapter's preferred `audio/webm;codecs=opus` recording format.

A private plugin directory symlinks the installed GStreamer plugins except files owned by `gstreamer1.0-plugins-bad`; `GST_PLUGIN_SYSTEM_PATH_1_0` and a separate registry select that directory. No host packages were removed. GTK is forced to X11 on an Xvfb display, `WAYLAND_DISPLAY` is removed, and a separate D-Bus session is used. The probe asserts its actual display before creating its window; subprocesses inherit the isolated environment.

| Plugins | Microphone track | Opus advertised | Recorder result |
| --- | --- | --- | --- |
| Exclude plugins-bad | live | yes | `NotSupportedError: The MediaRecorder is unsupported on this platform`, 0 bytes |
| Installed plugins-bad | live | yes | 48,862 bytes after two seconds |

WebKit emits `GStreamer element uritranscodebin not found. Please install it` in the failing case. `gst-inspect-1.0 uritranscodebin` identifies the installed element as `/usr/lib/x86_64-linux-gnu/gstreamer-1.0/libgsttranscode.so`, from gst-plugins-bad. Studio's `createAudioRecorder` chooses MediaRecorder because Opus is advertised. `startSegment` propagates the start failure into the generic microphone-error toast.

The reporter's exact installed packages were not available. This verifies a concrete failure with the reported symptom and distribution; it does not establish every possible cause of the toast.

## Package metadata

Ran pinned `@tauri-apps/cli` 2.10.1 `tauri bundle --bundles deb --no-sign --ci` with the changed configuration and an existing desktop executable. The native dependency SDK was supplied only for pkg-config discovery. This is a packaging test, not a fresh executable build. No package was installed on the user's computer.

Changed config:

```
Depends: gstreamer1.0-plugins-bad, libayatana-appindicator3-1, libwebkit2gtk-4.1-0, libgtk-3-0
```

Negative control: bundle with `bundle.linux.deb.depends` reset to an empty list, equivalent to the base config's omitted list:

```
Depends: libayatana-appindicator3-1, libwebkit2gtk-4.1-0, libgtk-3-0
```

The generated metadata adds the required plugin package while preserving Tauri's defaults. Both initial apt installation and the existing apt-based desktop updater resolve the dependency.

## Focused checks

- `node --experimental-strip-types --test studio/frontend/tests/pcm-recorder.test.ts`: 15 passed.
- `uv run --no-project --with pytest --with pyyaml python -m pytest tests/security/test_release_desktop_appimage.py -q`: 20 passed.
- `git diff --check`: passed.
- Independent review and pre-push dimensions: no actionable findings.

No Python, TypeScript, or Rust implementation changed; full lint/typecheck/build and GPU/model tests were not needed for this dependency-only diff. The native capture/recording path was exercised, but complete model transcription and a fresh desktop release build were not run.

## References

- Tauri additional dependencies: https://v2.tauri.app/distribute/debian/
- Pinned CLI preserves automatic dependencies: https://github.com/tauri-apps/tauri/blob/tauri-cli-v2.10.1/crates/tauri-cli/src/interface/rust.rs#L1273
- GStreamer transcode plugin: https://gstreamer.freedesktop.org/documentation/transcode/uritranscodebin.html
