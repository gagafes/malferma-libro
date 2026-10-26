<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

# Manual desktop smoke-test checklist

Use this checklist to try Malferma Libro in an ordinary graphical desktop
session. No programming or paid services are required. It describes checks
to perform, not desktops or features that have already been verified.

## Before you start

- Follow the [installation instructions](../README.md#installation-and-launch).
  Record the application version and full package version, such as application
  `0.1.1` and DEB `0.1.1-3`. The DEB filename or your system's package manager
  shows the package version. For a source build, record the commit instead.
- Choose a local test book you may freely share, preferably an EPUB with at
  least two chapters, several screens of text and a known embedded illustration.
  A cover alone does not exercise inline illustrations. No book upload is
  required. Mark checks missing suitable sample content **Not tested**.
- Record your distribution/version, desktop, screen scale, theme and interface
  language; include X11 or Wayland if known. Record any settings you change so
  you can restore them afterward.
- The shortcuts below are defaults. If you use custom shortcuts, use the
  active combinations shown in the main menu's shortcut reference or the
  corresponding buttons. You do not need to reset your keyboard profile.

Use **Pass** only after performing the action and observing its expected
result. Use **Fail** for a mismatch and **Not tested** when a check was not
performed, including unavailable sample content, hardware or optional tools.

## Core checks

Replace the result in each row you try. Close menus and dialogs, then click
the book content before testing reading keys; input fields and buttons keep
their normal keyboard behavior.

| ID / check | Action | Expected result | Result |
| --- | --- | --- | --- |
| S01 Installation and launch | Install the selected build, then launch Malferma Libro from the application menu. | Installation completes and a usable main window opens. If already installed, record installation as Not tested separately from launch. | Not tested |
| S02 Import and reading | Use the open-book button or Ctrl+O to import the test book. Read and scroll through several paragraphs. | The book is added to My books and opens with readable content. Scrolling responds without a persistent freeze. | Not tested |
| S03 Saved position | Stop at a memorable passage beyond the first screen, in another chapter if available. Close the main window, relaunch and use Continue reading or reopen that same book. | The saved chapter and reading passage are restored. Opening the library first is normal; automatic opening of the last book is a separate setting. | Not tested |
| S04 Table of contents | Open the contents with F9. Select a different chapter or heading, then close the sidebar. | The selected entry leads to the matching passage. In a narrow window the sidebar can overlay the book and close again. | Not tested |
| S05 Search | In Reading, press Ctrl+F and search for a word known to occur in the book. Select a result or press Enter, then use the return-to-position control. | Results lead to matching text; returning restores the position from before searching. Typing a query alone does not move the book. | Not tested |
| S06 EPUB/FB2 illustrations | Find a known embedded illustration, select it, try the viewer's zoom controls and close the viewer. | The image appears in the book and opens in a larger view. Zoom works, and closing returns to reading. | Not tested |
| S07 Text size | In a text book, try increase, decrease and reset in Accessibility, or Ctrl++, Ctrl+− and Ctrl+0. | Text changes size and reset restores size 20. The book's total reference-page count stays unchanged. | Not tested |
| S08 Day and night | Use the day/night button or Ctrl+Shift+D in both directions. | The window and text page switch between light and dark appearance with readable controls and the reading position preserved. | Not tested |
| S09 Keyboard navigation | Focus a passage away from the book's beginning and end. Try ↑/↓, ←/→, Page Up/Page Down and Alt+←/Alt+→. Use Tab and Shift+Tab to reach controls. | ↑/↓ scroll; ←/→ and Page keys move through the text; Alt+arrows change chapter. Navigation stops at book boundaries. Focus remains visible and controls are operable. | Not tested |
| S10 Fullscreen | Enter fullscreen with F11. If the top bar hides, reveal it with F10 or the pointer at the top edge. Leave with F11. | The book fills the window, reading tools remain reachable, and the normal window returns. Automatic hiding depends on settings and high contrast. | Not tested |
| S11 Narrow and maximized window | Make the window small, open Accessibility and scroll to its last control. Close it and maximize the window. | Toolbar and menu controls remain reachable. The scrollbar does not cover labels or buttons, and the book uses the available space. | Not tested |
| S12 Accessibility appearance | Open Accessibility with Ctrl+Shift+A. Try high contrast, bold text and line spacing, then restore your previous values. | Each setting changes the text presentation; controls remain readable and usable. Original scanned/image pages are not re-typeset. | Not tested |
| S13 Reading magnifier | Enable Reading area magnifier, try factors from 2× to 4×, move the pointer over the book, then disable it. | The magnified excerpt follows the pointer or shows the center when the pointer is outside the book. Book layout stays unchanged. The magnifier is session-only. | Not tested |
| S14 Screen scaling / monitors | If available, try 200% desktop scaling and moving the window between monitors. Reopen the application if your desktop requires it; restore the original setup. | Text and controls remain legible and reachable, with no overlap or clipped menus. Record the actual scales/screens used; otherwise mark Not tested. | Not tested |

## Optional checks

Missing Piper, a voice model, a screen reader, another monitor or an extra
book format is **Not tested**, not a failed application check. Test only the
configurations available to you.

| ID / check | Action | Expected result | Result |
| --- | --- | --- | --- |
| F01 Other formats | Repeat the relevant checks with available FB2, TXT, HTML/Markdown, PDF, DjVu or CBZ samples. For PDF/DjVu/CBZ, try zoom, reset and ←/→. Record each format separately. | For PDF/DjVu/CBZ, reset gives 100% page zoom and ←/→ opens the neighboring document page. Original image colors remain unchanged by day/night mode. Search and narration require text; CBZ and scans without a text layer have no OCR. | Not tested |
| P01 Piper narration | Only if Piper, a suitable voice and audio output are already installed, select the language/voice and read a short passage. Try pause, resume and stop. | Speech is audible. Pausing silences speech, resuming continues narration and stopping ends playback. Missing prerequisites need no installation for this checklist; see the [narration guide](MANUAL.en.md#narration). | Not tested |
| A01 Screen reader | If you already use a screen reader such as Orca, navigate the toolbar and Accessibility with the keyboard. Record its version and desktop/session. | Focused controls have meaningful spoken names and remain operable. Report the actual result for this setup only. | Not tested |

## Share the results

Submit the existing [test-report form](https://github.com/gagafes/malferma-libro/issues/new?template=03_test_report.yml).
Use its version and environment fields, and put the step IDs, results and
short observations in Results. Successful reports are useful too; keep
unperformed checks marked **Not tested**.

For each reproducible failure, search existing issues, then file or link a
separate [bug report](https://github.com/gagafes/malferma-libro/issues/new?template=01_bug_report.yml).
Include the step ID, actions, expected result and actual behavior. Link that
issue from your test report so different problems can be tracked separately.

Remove personal information from screenshots and logs. Do not upload private
books, passwords, access tokens or personal library data. A written description
is sufficient when you cannot share a sample.

The [user guide](MANUAL.en.md) describes the controls in detail. The project's
[validation record](../VALIDATION.md) distinguishes automated checks from
manual desktop testing; a checklist or CI run alone does not establish
compatibility with an untested desktop, screen reader or narration setup.
