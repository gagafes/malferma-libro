# Application screenshots

These PNGs show the actual Malferma Libro GTK4/libadwaita application running
on Debian 13 with an X11 virtual display, scale 100%, and English interface.
They capture the application window rather than a complete desktop session.
The screenshots preserve native window pixels without compositing a mock UI.

- `reading-light.png`: the day reading theme, an inline illustration and contents.
- `reading-dark.png`: the same book in the night theme.
- `library-light.png`: local EPUB and FB2 demonstration books with covers.
- `capture-manifest.json`: capture date, runtime versions, dimensions and SHA256.

## Sample content and licensing

The Ukrainian poem *Надія* (1880) is by Lesya Ukrainka (1871–1913).
Its historical spelling and accents follow the
[1892 edition transcription](https://uk.wikisource.org/wiki/Сторінка:Леся_Українка._На_крилах_пісень._1892.pdf/28).
The original poem is in the public domain. The original printed ornament
and other artwork from that edition are not included.

The sample book covers, landscape illustration and English demonstration
prose are created by `packaging/screenshots.py` and use GPL-3.0-or-later.
They are demonstration material for the reader. The screenshots and capture
script use the project's GPL-3.0-or-later license; existing font and UI library
licenses remain unchanged. No personal library or external catalog is used.

## Reproducing the captures

Install the application's regular Debian dependencies first (see the main
README), then the additional capture tools:

```sh
sudo apt install python3-cairo xvfb xauth dbus-x11 imagemagick adwaita-icon-theme fonts-noto-core
xvfb-run -a --server-args='-screen 0 1920x1200x24' dbus-run-session -- \
  /usr/bin/python3 -B packaging/screenshots.py --output docs/screenshots
```

Each scene runs in a fresh process with temporary XDG data, configuration,
cache and runtime directories. The regular personal library is not opened.
The script waits for covers and the reading illustration before capturing.
Native shadow and window extents may differ with GTK versions; the manifest
records the actual PNG and content dimensions. Rendering may vary with the
distribution's GTK, fonts and image libraries.

The manual **Capture screenshots** GitHub Actions workflow reproduces this
process in a `debian:13` container. The
[capture run](https://github.com/gagafes/malferma-libro/actions/runs/39259007086)
also checks the native interface geometry. Runtime application version 0.1.1 is shown;
the published DEB remains 0.1.1-1. The capture also uncovered a GTK flag-alias
compatibility fix and excessive expansion of library cover/card widgets in
current source; these fixes do not replace released assets.
