# Source Recovery

The working tree was reconstructed from the only preserved Debian package. Its Python modules were supplied in textual form: **47 modules**, installed resources, compiled translations, manuals, license notices, icons, and desktop metadata were extracted from the package.

This is a recovery of available materials, not a restoration of the deleted repository in its entirety. The Debian package did not contain the previous tests, original build scripts, editable PO/POT catalogs, or separate logo-production materials. The commit history and the remote GitHub repository were not preserved in the package.

The current build scripts, project configuration, and tests were created anew. Editable PO catalogs were reconstructed from MO files: source-string and translation pairs are available, but the original translator comments and editing history cannot be recovered from MO files. Font license notices and the logo owner's permission were preserved. The available SVG files contain vector outlines and can be edited directly.

At the owner's decision, the first reconstructed release was assigned version **0.1.0**. After further development, the current application version is **0.1.1**. The project directory is named `malferma-libro`, the Python module is `malferma_libro`, and the user command is `malferma-libro`. Older builds and archives are not part of the current project.

The source tree for the current release is intended to build Debian package version **0.1.1-2**. Earlier reports of hundreds of tests do not represent verification results for this reconstructed tree. Current verification results and limitations are recorded in [VALIDATION.md](../VALIDATION.md).

For the original Russian note, see [RECOVERY.md](../RECOVERY.md).
