# Malferma Libro — user guide

Version 0.1.0. An application for Debian 13 built with GTK 4 and libadwaita.
This English guide is bundled with the application and is available without
an internet connection. Open it from the main menu, with F1 by default, or with
`malferma-libro --manual=en`.

The complete guide is available in Russian, English, German and Ukrainian.
The language selector in the guide defaults to automatic selection and follows
the interface language immediately. Other interface languages use the English
guide. In a terminal, `--manual` selects the language from the locale environment;
`--manual=ru`, `--manual=en`, `--manual=de` and `--manual=uk` select it explicitly.

The shortcuts in this guide refer to the default profile. If you have
customized them, open “Keyboard shortcuts” in the main menu to see
the currently active bindings.

## First launch and opening books

Start Malferma Libro from the applications menu or with `malferma-libro`.
Use the open-book button in the top bar or press Ctrl+O. You can select
several files at once. Supported formats are EPUB, FB2, FB2.ZIP, TXT, PDF,
DjVu (including .djv), HTML/XHTML (.html, .htm, .xhtml), Markdown (.md,
.markdown) and CBZ comics. The file chooser uses the system
portal; if the portal is unavailable, the application opens a GTK dialog.

Books are copied into your personal library. Moving the original file after
import does not prevent you from reading the saved copy. Importing identical
bytes again does not create another entry: the application offers to open
the existing book with its previous bookmarks and reading position. When
you open several books, all of them are added to the library; return to
the others from “My books”.

Covers are selected automatically from images embedded in EPUB and FB2,
the first suitable image among the first 32 CBZ pages, or image URLs supplied by an OPDS catalog.
Thumbnails are prepared
in the background and saved in a local cache. The application does not
query outside cover-search services by ISBN or book title. A missing
or unsuitable cover does not prevent opening or reading the book.

Thumbnails appear in the library and the continue-reading card. In an OPDS
catalog, images are requested for rows that enter the visible part of the
list; saved covers are reused from the cache. A standard book icon appears
while no cover is available. Failed remote cover requests are remembered
for the current session without a retry loop; restarting the application
and opening the catalog lets it try again.

Examples of launching from a terminal:

```sh
malferma-libro
malferma-libro "Книга с пробелами.epub" "Другая книга.fb2"
malferma-libro -- -книга.txt
```

Quotation marks keep a filename containing spaces together as one argument.
After `--`, all arguments are treated as filenames: a file named `--version`,
for example, does not trigger version output. The only launch command is
`malferma-libro`.

## Main window

The top bar contains book-opening controls, search,
fullscreen mode and the main menu. In the reader it also contains the table
of contents, previous and next navigation, bookmarks, the “Accessibility”
menu and additional page tools. The accessibility menu brings together
narration and reading aids. Hold the pointer over a button to read its tooltip.
A command that is unavailable in the current section is disabled or hidden.

Related commands are grouped: opening and navigation are on the left,
search and book tools are nearer the center, day/night and fullscreen are
beside each other, and Accessibility and the main menu are at the outer edge.
One previous/next pair stays in the toolbar at every window width.
The table of contents is the sole chapter list. The three text-size commands
are in “Accessibility”, without a second size menu. The page tools menu
appears only for PDF, DjVu and CBZ. Keyboard shortcuts and mouse gestures
remain available.

Open these sections from the first group in the main menu:

- “My books” — imported books, with search by title and author.
- “Reading” — the open book and its saved position.
- “Online libraries” — OPDS catalogs and book downloads.

The default shortcuts are Ctrl+1, Ctrl+2 and Ctrl+3 respectively.
Interface text is 15% larger than the system font and follows its family
and desktop scale. Book text size is configured separately.

The center of the header shows the book title and progress. Completion
messages appear briefly over the window. A compact page number appears
at the bottom of the reading area. There is no permanent bottom row of
buttons: most of the space is devoted to the book.

The window uses a thin border and a light shadow. The outer border is hidden
when maximized or fullscreen. You can still resize the window by dragging
its edges; high-contrast mode keeps the outline clearly visible.

## Continuing reading and organizing the library

In “My books”, the “Continue reading” card returns to the last successfully
opened book and its saved position. Merely adding a file to the library does
not replace that book. The card is hidden until a book has been opened.

The application starts in the library by default. You can enable
“Open the last book at startup” in Settings. Opening an explicitly supplied
file or choosing another book takes precedence over this automatic action.

Filters and sorting are in a popover on the library's top bar. Show all books
or filter by “Not started”, “Reading” or “Finished”; sort by recent opening,
author or title. With “Recent” sorting, previously opened books appear before
imports that have not yet been opened. Library search checks the title,
author and format.

The menu beside an individual book lets you change its status manually.
Opening a book for the first time changes “Not started” to “Reading”. The
percentage shows the saved position, while “Finished” is set manually:
reaching the end of the book does not change this status automatically.

## Reading, the table of contents and search

Choose a book in the library. The application restores its chapter and
reading position. Your position is saved automatically as you read,
navigate and close the window. EPUB, FB2, TXT, HTML/XHTML and Markdown use
chapter navigation; PDF, DjVu and CBZ use pages. The arrow buttons and Alt+← / Alt+→ move
to the adjacent chapter or page. Navigation stops at the book's boundaries.

The bottom of the reading area shows pages for the whole book. The counter
updates when you scroll with the mouse or keyboard, or navigate using the
table of contents, search or bookmarks. If the visible text spans several
reference pages, it shows a range, such as “Pages 12–13 of 640”.

EPUB, FB2, TXT, HTML/XHTML and Markdown use continuous reference page numbers:
each page contains 1800 Unicode characters, including spaces and line breaks.
Chapter texts are counted consecutively, without inserting empty pages or
padding the end of a chapter. A new chapter can continue on the same page.
Changing the font, line spacing or window size does not change page numbers
or the total page count, although the visible range may change. These are
not the page numbers of a particular printed edition. The counter's tooltip
says “Reference pages for the whole book”.

PDF and DjVu retain the document's original pages; CBZ uses images in reading
order. Their page numbers are independent of zoom and scrolling within an
image.

Open the table of contents with its top-bar button or F9. Select an entry
to go to it. In a narrow window the sidebar overlays the book and can be
closed with the same button. In a wide window it occupies a narrow strip.

The sidebar preserves the hierarchy of chapters and subsections, with notes
grouped separately. An EPUB table-of-contents entry can point to a particular
heading within a chapter: selecting it scrolls to that position rather than
just opening the beginning of the file. FB2 notes are retained and available
in the table of contents.
HTML/XHTML and Markdown headings also retain their hierarchy in the table
of contents. They point within a single text document; selecting an entry
scrolls to the corresponding heading.

Ctrl+F opens search for the current section:

- In the library, search filters books by title, author and format.
- While reading, search checks the whole book, including chapters you have
  not yet opened. Results show a chapter title and a short text excerpt.
- In PDF and DjVu, search checks the pages' text layers one at a time.
  It does not generate images of every page or perform OCR. A match opens
  in the page-text panel; it is not a highlighted region on the scanned image.
- CBZ contains page images without a text layer. Searching their contents
  and OCR are not available.
- In a catalog, search is available if the catalog supplies a compatible
  search template.

Search and additional tools open when needed and do not permanently reduce
the reading area's height. Escape closes an open popover.

Typing a query fills the results list without moving the book. Select a
result or press Enter to go to a match; Shift+Enter and the previous-match
button move backward. The next- and previous-match buttons cycle through
the results. Beside them is “Return to the position before searching”, which
restores the chapter or page and position where searching began in that book.

The list displays the first 200 matches. If there are more, a message asks
you to refine the query. Search ignores letter case; the original characters
are selected correctly even when case conversion expands a character,
as with ß → ss. Cancel search with its own button or in the list of background
operations. If the text of some pages could not be read, the list reports
this while keeping the available matches from other pages visible. You can
view a scan without a text layer, but cannot search for words in its image.

## Text size and appearance

The day/night button in the top bar or Ctrl+Shift+D switches both the window
and the book page between light and dark appearance. Ctrl+Shift+В also works
with the Russian layout. The choice is saved. Your reading position is
preserved, and paused narration does not resume by itself. Original PDF/DjVu/CBZ
page appearance remains unchanged. System appearance and sepia are
still available in the full settings; the button explicitly selects day
or night mode.

The “Accessibility” menu in the reader's top bar provides three buttons:
decrease text size, restore the standard size and increase text size.
Their keyboard equivalents are Ctrl+−,
Ctrl+0 and Ctrl++. For text books the standard size is 20; Settings provides
a range of 12–96. For PDF, DjVu and CBZ the same buttons change page zoom:
the standard zoom is 100%, with a range of 25–300%.

Open “Settings” from the main menu or press Ctrl+,. Window and page
appearance are configured separately:

- The window can follow the system or use light or dark mode.
- Symbolic icons follow the system theme.
- Book background: system, day, sepia or night.
- Book font: system, Noto Serif, Noto Sans or Liberation Serif. Additional
  bundled fonts help display other writing systems.
- Maximum text width: 480–2400 logical pixels, with a default of 760.
  Text is centered on a wide monitor; in a narrow window the column shrinks
  to the available width.
- Page brightness: 30–100%. This dims the book's content rather than changing
  the monitor's backlight. Other windows and system settings are unaffected.

The interface language changes as soon as you select it in Settings. The
open book and position are preserved. There are 49 supported languages and
script variants. Panels change direction for languages written from right
to left; the direction of book paragraphs follows their text independently
of the menu language.

## Fullscreen mode and monitors

Press the fullscreen button in the top bar or F11. Press it again to return
to a normal window. Escape first closes a popover or cancels a gesture;
if neither action is needed, it leaves fullscreen mode.

While reading in fullscreen, the top bar hides automatically after about
two seconds of inactivity. To reveal it, move the pointer into the top
24 logical pixels of the window, press F10, or use Tab to reach its controls.
The bar stays visible while you use its buttons or have an open menu, dialog
or gesture. High contrast also keeps it visible. You can disable automatic
hiding in Settings; in a normal window and in other sections, the bar remains
in place.

GTK accounts for monitor scaling. When you move the window between screens
with different scaling, text stays in logical units and the PDF/DjVu/CBZ page is
rendered again for the display's pixel density. On a large screen you can
increase the column width in Settings or keep it narrow for comfortable
reading. There is no need to set global GDK_SCALE variables.

The application processes only the requested PDF/DjVu/CBZ page. The raster is
limited to 4096 pixels on its longest edge and 12 MiPixels. On an 8K display
or at high zoom, the image may be enlarged from this bounded raster: the
page retains its size, but detail is not unlimited. The original document
is unchanged.

## Mouse-gesture navigation

In the book area, hold the right mouse button and make a clear horizontal
movement:

- Left — next chapter or page.
- Right — previous chapter or page.

Navigation happens when you release the button, once per gesture. Short,
mostly vertical and diagonal movements do not turn the page. Escape cancels
the current gesture. With gestures enabled, a brief right click opens the
copying and text-selection menu. With gestures disabled, the text widget's
standard context menu remains available.

Turn gestures off in the “Accessibility” section of Settings. The navigation
buttons and Alt+← / Alt+→ work whether gestures are enabled or not.

## Accessibility

The “Accessibility” button in the reader's top bar opens a compact menu
with text size, high contrast, bold text, line spacing from 1.0 to 2.0,
a low-vision preset and narration controls. Appearance options can also
be changed in Settings. Ctrl+Shift+A opens the menu even when the top bar
is hidden in fullscreen; Ctrl+Shift+Ф also works with the Russian layout.
The narration-language and text-size controls sit below their labels.
The scrollbar has its own space beside the content. The menu height fits
the window; scroll to reach the tools farther down.
The preset applies text
size 32, Noto Sans, bold text, high contrast, line spacing of 1.5 and a column
width of 1000. For an open PDF/DjVu/CBZ document it raises zoom to at least 150%.
You can adjust each setting separately afterward.

The same menu lets you enable the “Reading area magnifier” and choose
between 2× and 4× magnification. It enlarges part of the displayed page,
follows the mouse pointer over the reading area; otherwise it magnifies
the center. It does not change the text-size setting, line
wrapping or the original PDF/DjVu/CBZ layout. Enabling the magnifier lasts
for the current session only: turn it on again after restarting the application.

Font and line-spacing settings affect text books and extracted page text;
they do not change the fonts in PDF/DjVu scans. Use zoom for a scan or CBZ
page. High
contrast applies to text; it does not turn the original document image into
text or perform OCR.

Tab and Shift+Tab move focus between available controls; Enter or Space
activates the selected button. Buttons have text labels for GTK accessibility
tools. Compatibility with a particular Orca and desktop configuration depends
on the installed AT-SPI infrastructure; Piper narration does not replace
the system screen reader.

## Narration

Narration uses Piper exclusively and works locally once the runtime is
installed and the required voice model has been downloaded. Book text is
not sent online. Models are not included in the application package and
are downloaded separately at your request; the catalog offers only models
whose free licenses have been checked.

Install Piper in a separate per-user Python environment, rather than using
`sudo pip` with Debian's system Python. Audio playback requires `paplay`
from `pulseaudio-utils` or `aplay` from `alsa-utils`. A typical setup with
PulseAudio or PipeWire is:

```sh
sudo apt install python3-venv pulseaudio-utils
piper_env="${XDG_DATA_HOME:-$HOME/.local/share}/malferma-libro/piper"
python3 -m venv "$piper_env"
"$piper_env/bin/python" -m pip install "piper-tts==1.8.0"
```

The application discovers this environment automatically with the default
data location. If XDG_DATA_HOME is set, use an absolute path.
`PIPER_PYTHON` can explicitly select another Python that has Piper installed.
Changes to `PIPER_PYTHON` apply when the application is launched again.
Voice models become available without restarting.

Supported languages are Russian, Ukrainian, English, German, French, Spanish,
Italian and Portuguese. The selected language needs a compatible installed
Piper model. The checked download catalog contains voices for English,
Ukrainian, German, French, Spanish and Italian. Russian and Portuguese
currently require adding a local model; the application does not certify
the license of a file you select yourself.

Open “Settings” → “Read aloud”, or use “Piper voices” in the accessibility
menu, and choose a language and voice. The voice
list is filtered by language. Selecting a specific voice sets its language;
changing to an incompatible language restores automatic voice selection.
For a catalog model, use the download button: no model is downloaded
without this action. Download progress and cancellation are available in
the background-operation list; the voice is available after completion.
To add a local voice, use the add-voice button and select its `.onnx` file; the
matching `.onnx.json` must be beside it. Check the local model's license
and your permission to use it separately.

The sample-preview button plays a short example with the chosen voice
offline. It pauses any current book narration and leaves it paused.
The Piper installation-instructions button opens this guide. Downloaded
models are saved in `voices/` under the application data directory.

Choose a language and speed from 44–250% in the
“Accessibility” menu in the reader's top bar.
“Detect from chapter text” tries to identify one of these eight languages;
for short or ambiguous text, it is better to select the language manually.
Narration in other languages is not claimed; this does not restrict interface
translations or the display of books.
100% is the model's normal speed. Percentages control relative synthesis
speed; the actual words per minute depend on the model and text.

The “Accessibility” menu contains controls to start reading from the current
position, pause, resume and stop. Space starts, pauses and resumes narration
when focus is in the reading area rather than an input field or button.
Ctrl+Shift+S also stops narration. Leaving the reader section pauses narration.
Manually switching to a different chapter stops the previous narration.

For PDF and DjVu, narration uses the current page's text layer. A page that
contains only an image can be viewed, but its text cannot be searched or
read aloud. There is no automatic text recognition here.
CBZ has no text layer and cannot be read aloud.

## Bookmarks

Open the bookmarks menu in the top bar and choose to add a bookmark, or
press Ctrl+B in “Reading” with a book open. A bookmark saves the current
chapter or page and position. Select it in the same menu to return to it.
For a text book, the list shows the chapter title and a readable excerpt
near the saved position. For PDF/DjVu, it shows the page number, starting
from 1, and selected text; if nothing is selected, it uses the beginning of
the page's text layer. A scan without text retains its page-number label.
Within a PDF/DjVu page, the saved position refers to image scrolling,
not a character offset in the text.
For CBZ, a bookmark saves the image page and scroll position. Its label
contains a page number without a text excerpt.

The note button beside a bookmark opens an editor with a 2000-character
limit. A counter shows the length; saving is disabled if the limit is
exceeded. Saving changes only that bookmark's note; empty text removes
the note. If the bookmark has been deleted or another book is open, the
editor does not apply changes to a different entry. The delete button
beside a bookmark removes only that bookmark.

Bookmarks and the last reading position are saved locally. Deleting the
original book file after import does not remove the library's copy or
its bookmarks.

## Online OPDS libraries

Open “Online libraries”, then the connection button in the top bar.
Press “+”, enter a name and the complete URL of a public OPDS 1.x catalog,
such as the address of a Calibre catalog on your home network. Select
the catalog and press “Connect”.

Browse the catalog's sections, use its search if available and move between
pages with the navigation buttons. Choose an appropriate book download.
Once downloaded, the book is imported into your personal library and is
available without a connection to the catalog.
Supported download formats match those for local file imports.

Removing a catalog with “−” removes it from the connection list; previously
imported books remain. HTTP and HTTPS are supported, without a password in
the URL. Authenticated catalogs, OPDS 2 and DRM are not supported.

## Background operations, cancellation and errors

Book opening and imports, downloads, whole-book search and page preparation
run in the background. The “Background operations” button in the top bar
shows current tasks, available progress and cancellation buttons. Not every
stage has a known percentage: sometimes an activity indicator is displayed.

Cancellation stops further steps at the next safe opportunity. A network
request or external processor that is already running may finish later;
cancellation does not instantly interrupt every system call. Books already
imported and other changes already saved remain in the library. A canceled
or outdated result must not switch the open book.

An error message explains the action and cause. Where possible, “Retry”
starts the action again. If a file is missing, use “Choose a book…” to
select an available copy. For a network error, check the connection and
catalog address; for an access error, check permissions and disk availability.

## Keyboard shortcuts

To change keys, open “Settings” → “Keyboard shortcuts”. Under “Mode”,
choose “Default” or “Custom”. The custom profile inherits every default
binding that you have not changed.

1. Select “Change shortcut” beside an action.
2. Press the new key combination in the dialog. “Disable” removes that
   action's keyboard binding; “Default” restores its original keys.
3. Select “Save” to apply the change immediately and keep it between
   sessions. “Cancel” or Escape closes the dialog without changes.

Replacing a binding removes the action's previous default keys, including
their Russian-layout aliases. Conflicting shortcuts are rejected, including
Latin and Cyrillic bindings on the same physical key. Escape, Tab, standard
Ctrl+C/V/X/A/Z/Y editing commands, ordinary typing and unmodified navigation
keys are reserved. Use Ctrl, Alt or a function key; Super combinations are
not supported. Unmodified Space is available only for narration and acts
when the reading area has focus.

Changing “Mode” takes effect immediately. Switching back to “Default” keeps
your custom profile so that you can enable it again. “Reset all shortcuts”
immediately clears all custom bindings and selects the default profile;
it does not change other application settings. “Keyboard shortcuts” in the
main menu shows the bindings that are currently active. The table below
lists the defaults; normal GTK commands, including Escape, are independent
of the profile.

The commands below apply to the main window. Open dialogs and input fields
retain normal GTK behavior; reading commands, including adding a bookmark
and stopping narration, require the “Reading” section to be active with
a book open.

| Shortcut | Action |
| --- | --- |
| Ctrl+O | Open one or more books |
| Ctrl+F | Search the current section |
| Ctrl+, | Settings |
| Ctrl+Shift+A | Open Accessibility, even when the top bar is hidden |
| Ctrl+Shift+D | Switch day / night mode |
| Ctrl+1 | My books |
| Ctrl+2 | Reading |
| Ctrl+3 | Online libraries |
| Ctrl+B | Add a bookmark in the open book |
| Ctrl+− / Ctrl++ | Decrease / increase text size or PDF/DjVu/CBZ zoom |
| Ctrl+0 | Standard text size or 100% zoom |
| Alt+← / Alt+→ | Previous / next chapter or page |
| F9 | Show or hide the table of contents |
| F11 | Enter or leave fullscreen mode |
| F10 | Reveal the hidden top bar and focus its buttons |
| Escape | Close a menu, cancel a gesture or leave fullscreen |
| Space | Narrate / pause / resume with focus in the reading area |
| Ctrl+Shift+S | Stop narration |
| F1 | Open this guide |
| Ctrl+? (Ctrl+Shift+/) | Show keyboard shortcuts |
| Ctrl+Q | Close the main window |

Opening a book focuses the reading area so that keyboard scrolling is ready
immediately. To return to reading after using other controls, click the text
or page image. Toolbar buttons, the table of contents, search field, document
text layer, other inputs and open menus or dialogs retain their own key behavior.

| Reading keys | Action |
| --- | --- |
| ↑ / ↓ | Scroll a small distance up / down |
| ← / → | Previous / next page: 90% of the viewport in text books; the adjacent document page in PDF/DjVu/CBZ |
| Page Up / Page Down | Scroll by 90% of the viewport height; at an already reached boundary, move to the previous / next chapter or document page |
| Home / End | Beginning / end of the current chapter or document page |
| Ctrl+Home / Ctrl+End | Beginning / end of the whole book |

← / → keep a 10% overlap in text books; at an already reached boundary,
they open the bottom of the previous chapter or the top of the next one.
In PDF, DjVu and CBZ they immediately open the adjacent page at its top,
even when the current page is zoomed and scrolled. Key directions stay the
same in LTR and RTL books: ← goes back, → goes forward. Page numbers
remain continuous across the whole book.
↑ / ↓ do not change chapters. Alt+← / Alt+→ move directly to the adjacent
chapter or page. Page Up opens the bottom of the previous chapter or page;
Page Down opens the top of the next one. Navigation stops at the book's ends.
A custom binding for a Ctrl combination takes precedence over scrolling.
Shift variants keep GTK's normal text-selection behavior; Ctrl+C copies
selected text where the widget supports it. In the book-search field, Enter
moves to the next result and Shift+Enter to the previous one.
Numeric-keypad navigation keys work with Num Lock off; with Num Lock on,
digits remain digits. These reading commands also appear in the shortcut
reference; a Ctrl combination replaced by a custom binding is not shown
as a scrolling command.

## Help in a terminal

```sh
malferma-libro --help
malferma-libro --manual
malferma-libro --manual=ru
malferma-libro --manual=en
malferma-libro --manual=de
malferma-libro --manual=uk
malferma-libro --license
malferma-libro --version
man malferma-libro
```

The `man` command is provided by the optional `man-db` package. If it is
missing, install it with `sudo apt install man-db` or use `--manual` and
the built-in help, which work without `man-db`.

The application's informational commands require no GTK, running graphical
session, audio device or network access. `-h` is equivalent to `--help`.
Concise help uses Russian, German or Ukrainian for those locales and English
for all others. `--manual` selects the complete guide from the locale
environment, with the same English fallback. Use `--manual=ru`, `--manual=en`,
`--manual=de` or `--manual=uk` to choose one of the four guide languages
explicitly. In the graphical guide, the language selector defaults to
automatic selection, which follows interface-language changes immediately;
you can also choose any of the four languages there. `--license` prints
the complete original GNU GPL v3 text, rather than a summary.

GTK 4 chooses the graphical session from the system environment, including
DISPLAY and WAYLAND_DISPLAY. Unknown options are rejected with exit code 2.
Informational commands exit without opening any supplied books. Exit code 0
means success; code 1 indicates that the application could not start or
a required resource could not be read. Only one informational mode can be
selected in a single invocation.

## Data storage and backups

New installations store data in `~/.local/share/malferma-libro/`, or
`$XDG_DATA_HOME/malferma-libro/` when XDG_DATA_HOME is absolute. If the new
directory does not yet exist but the previous `otkrytaya-kniga` directory
already exists under the same data home, the application keeps using it to
preserve access to the existing library. User books are not automatically
moved or deleted.

It contains `library.json` with the library, settings, reading statuses,
last opened book, bookmarks, notes and reading positions; the recovery copy
`library.json.bak`; `books/` with managed book copies; the local cover cache
`covers/`; Piper voice models in `voices/`; and the temporary download
directory `downloads/`.

For a complete backup, close the application and copy the entire data
directory. Close the application before restoring it as well. Do not
replace a single JSON file without the corresponding books: entries refer
to local copies. The application can recover corrupted metadata from
the recovery copy and retains the damaged file separately for inspection.
If it reports a newer data schema, use a compatible application version.

Removing the package with APT does not delete the personal library from
your home directory. Cross-device synchronization and cloud storage
are not implemented.

## Format limitations and troubleshooting

EPUB and FB2 are converted into text chapters. Original EPUB CSS, inline
illustrations, interactive elements and exact layout are not reproduced.
Covers are extracted separately for the library; showing them does not add
support for images within EPUB text.
TXT is displayed as text; PDF and DjVu preserve the page image and element
positions. DRM-protected books are not supported. The graphical interface
does not yet provide password entry for protected PDFs. Standalone DjVu
files and bundled books are supported; external-component documents must
be bundled beforehand.

If a book will not open, check its format, file access and the application's
message. PDF requires `poppler-utils`; DjVu requires `djvulibre-bin`.
PDF/DjVu source files are limited to 64 MiB and 10,000 pages. These limits
protect application resources without changing the original book.

HTML/XHTML is converted to text without JavaScript execution, browser layout,
CSS or external file/image loading. Markdown uses CommonMark through
`markdown-it-py`: headings, lists, quotations, code blocks and emphasized
content become readable text. Links retain their labels, images their alt
text, and raw HTML is displayed literally. GFM extensions, including tables
and footnotes, are not claimed. HTML/XHTML and Markdown files are limited
to 64 MiB, with at most 32 × 1024 × 1024 decoded characters.
Complex markup nesting can exceed separate parser limits even in a smaller file.

CBZ is a ZIP archive of page images. PNG and JPEG are supported; WebP requires
a suitable installed GdkPixbuf loader. Pages use natural path/filename order,
so 2 comes before 10. Hidden files and `__MACOSX` entries are skipped.
ComicInfo.xml can supply a title and author. Images are loaded one page at a
time; CBZ has no text, search or narration. The archive limit is 512 MiB,
expanded entries total at most 1 GiB, with at most 10,000 pages and 20,000 ZIP
entries. Each source image is limited to 32 MiB, 32 MiPixels and 16,384 pixels
on either edge. Display rendering has the shared limit of 4096 pixels on
the longest edge and 12 MiPixels.

EPUB/FB2 and OPDS covers support PNG and JPEG up to 4 MiB, with neither dimension above
4096 pixels and at most 4 MiPixels in total. Unsupported, oversized
or damaged images are skipped; the book itself remains available.
A CBZ cover is prepared separately from the first valid image among the
first 32 pages, scaled to at most 1024 pixels on the longest edge. Source-page limits are listed
above; later pages remain available for reading.

If the interface will not start, Debian 13 requires `python3-gi`,
`gir1.2-gtk-4.0` and `gir1.2-adw-1`; the vector logo requires
`librsvg2-common`. When running from source, use the system
`/usr/bin/python3`; Markdown requires `python3-markdown-it`.
Concise help and the guide are available without these
graphical dependencies. If narration is unavailable, check Piper in the
selected Python environment, the installed model for the required language,
and `paplay` or `aplay`. If PDF/DjVu search is unavailable,
check for a text layer. If OPDS will not open, check the network and make
sure the URL identifies an OPDS 1.x catalog rather than an ordinary library
web page.

## Licenses and application information

The source code is distributed under GPL-3.0-or-later. The complete GNU GPL v3
text is supplied in LICENSE and is available with `malferma-libro --license`.
The “About” window shows the standard GPL notice. Permission to use a later
GPL version is stated in the project's licensing metadata.

The logo and derived icons, including vector artwork, are distributed under
GPL-3.0-or-later with the project owner's confirmation; the permission record
is in LOGO_LICENSE.md. Fonts retain SIL OFL 1.1; their license texts and
attributions are in FONT_LICENSES.md and the font files. AppStream metadata
is licensed under CC0-1.0. Resource origins and the licensing review are
described in LICENSE_AUDIT.md.
Piper and voice models retain their own licenses. Model sources and terms
are described in PIPER_LICENSES.md; the application license does not
relicense separate voice models.

Third-party system libraries retain their own licenses. The program is
provided without warranty to the extent specified by the GPL.

This guide is distributed under GPL-3.0-or-later.
