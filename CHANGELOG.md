# Changelog

Each release's section is what a running copy shows when it offers that version (the update
offer's notes), so write it for the person using uCANdo. Older history: README → Release history.

## [1.6.0] — 2026-11-26

### New
- **Updates itself.** Pin `uCANdo.exe` (the launcher) once: each start checks for a newer version,
  offers it with these notes, and *Update* installs it beside this one and restarts into it. Your
  data stays where it is. Hold Shift while starting `uCANdo.exe` to start an earlier version.
- **A new look.** Auto / Light / Dark theme, a resizable side rail, and uCANdo in its own window
  with its own taskbar button. *Settings → Views* hides any view you do not use.
- **TX replay, faster to set up.** Upload several logs at once as a playlist, see which file is
  being sent, and replay PCAN-View `.trc` files as well as Vehicle Spy and `.asc` logs.
- **Transmit signal: Tiles or Bytes.** Every transmitted signal as a tile, as the device's cloud
  panel shows it (pin the ones your cloud shows), or every transmitted ID byte by byte with the
  changed bytes lit.
- **TX rides out a lost bus.** Unplug the device under test, or let the bus go bus-off, and
  playback waits for the bus, resets the adapter and carries on by itself. Only *Stop* ends the
  wait. The bus chip shows the adapter's error state.
- **Your name, once.** The first start asks your name, to greet you. *Settings → Usage
  reporting* shows what is shared: never CAN data, logs, DBCs or VINs.

### Fixed
- Closing uCANdo's console window now ends its usage session properly.
