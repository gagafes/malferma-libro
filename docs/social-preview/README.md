# GitHub social preview

`social-preview.png` is a promotional card for links to this repository. It is
1280 × 640 pixels and smaller than 1 MB, ready for GitHub's social preview.
It combines the official logo, a decorative background and a proportionally
scaled application screenshot. It is not a raw application capture; the
screenshot's interface has not been redrawn.

## Sources and licensing

- `social-preview.svg`: editable composition with embedded image resources.
- `background.png`: decorative background generated with OpenAI image generation.
- Logo: [`app-icon.svg`](../../src/malferma_libro/assets/branding/app-icon.svg),
  covered by the project's [logo license](../../LOGO_LICENSE.md).
- Application view: [`reading-light.png`](../screenshots/reading-light.png).
  See the [capture environment and sample-content licenses](../screenshots/README.md).

The layout and SVG were assembled with assistance from OpenAI Codex. The
preview artwork and its source files use the project's
[GPL-3.0-or-later license](../../LICENSE), consistently with the existing logo
and screenshot grants. Existing font and UI-library license terms remain
unchanged.

## Set the repository preview

Open the repository's **Settings → General → Social preview → Edit →
Upload an image**, then choose `social-preview.png` and save the change.
Adding these files to the repository does not activate the preview setting.

## Re-export

The text uses Noto Sans (`fonts-noto-core` on Debian). Keep that font
installed when exporting to preserve the layout.

With Inkscape installed, run this command from the project root:

```sh
inkscape docs/social-preview/social-preview.svg --export-type=png --export-filename=docs/social-preview/social-preview.png --export-width=1280 --export-height=640
```

Check that the exported PNG remains smaller than 1 MB before uploading it.
