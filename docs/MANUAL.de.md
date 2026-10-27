# Malferma Libro — Benutzerhandbuch

Version 0.1.1. Eine Anwendung für Debian 13 und Ubuntu 24.04 mit GTK 4
und libadwaita.
Dieses vollständige deutsche Handbuch wird mit der Anwendung geliefert und
ist ohne Internetverbindung verfügbar. Öffnen Sie es im Hauptmenü, standardmäßig mit F1
oder ausdrücklich auf Deutsch mit `malferma-libro --manual=de`.

Vollständige Handbücher stehen auf Russisch, Englisch, Deutsch und Ukrainisch
bereit. Im Handbuchfenster ist „Oberflächensprache“ standardmäßig ausgewählt.
Dabei folgt das Handbuch der aktuellen Oberflächensprache sofort;
für andere Oberflächensprachen wird Englisch verwendet. Im selben Menü
können Sie eine der vier Handbuchsprachen ausdrücklich wählen.
Im Terminal wählt `malferma-libro --manual` die Sprache automatisch anhand
der Sprachumgebung. Mit `--manual=ru`, `--manual=en`, `--manual=de` oder
`--manual=uk` lässt sie sich ausdrücklich festlegen.

Die Tastenkürzel in diesem Handbuch beziehen sich auf das Standardprofil.
Wenn Sie eigene Kombinationen festgelegt haben, zeigt „Tastenkombinationen“
im Hauptmenü die aktuell wirksamen Kürzel.

## Erster Start und Öffnen von Büchern

Starten Sie Malferma Libro über das Anwendungsmenü oder mit `malferma-libro`.
Klicken Sie in der oberen Leiste auf die Schaltfläche zum Öffnen von Büchern
oder drücken Sie Ctrl+O. Sie können mehrere Dateien gleichzeitig auswählen.
Unterstützt werden EPUB, FB2, FB2.ZIP, TXT, HTML/XHTML, Markdown, PDF, DjVu
und CBZ. HTML-Dateien dürfen auf .html, .htm oder .xhtml enden,
Markdown-Dateien auf .md oder .markdown und DjVu-Dateien auch auf .djv.
Die Dateiauswahl verwendet das Systemportal. Falls dieses
nicht verfügbar ist, öffnet die Anwendung den GTK-Dateidialog.

HTML/XHTML und Markdown werden als Text eingelesen. Markdown verwendet
CommonMark ohne zusätzliche GFM-Tabellen oder Fußnotenerweiterungen.
Die Anwendung führt keine Skripte aus und
lädt keine verknüpften Webseiten, Bilder oder anderen externen Ressourcen.
CBZ ist ein ZIP-Archiv mit Bildseiten. Seine Seiten werden bei Bedarf
angezeigt; sie erhalten keine automatische Texterkennung.

Bücher werden in Ihre persönliche Bibliothek kopiert. Sie können die
Originaldatei nach dem Import verschieben und die gespeicherte Kopie
weiterlesen. Ein erneuter Import identischer Dateiinhalte erzeugt keinen
zweiten Eintrag: Die Anwendung bietet an, das bereits gespeicherte Buch mit
seinen bisherigen Lesezeichen und seiner Leseposition zu öffnen. Wenn Sie
mehrere Bücher öffnen, werden alle der Bibliothek hinzugefügt. Die anderen
Bücher erreichen Sie anschließend im Bereich „Meine Bücher“.

Titelbilder werden automatisch aus eingebetteten Bildern in EPUB und FB2,
aus der ersten geeigneten unter den ersten 32 Bildseiten eines CBZ oder aus den von einem
OPDS-Katalog angegebenen Bildadressen übernommen.
Vorschaubilder werden im Hintergrund aufbereitet und lokal zwischengespeichert.
Die Anwendung fragt keine externen Titelbild-Suchdienste anhand von ISBN
oder Buchtitel ab. Fehlende oder ungeeignete Titelbilder verhindern weder
das Öffnen noch das Lesen des Buches.

Vorschaubilder erscheinen in der Bibliothek und auf der Karte zum Weiterlesen.
In OPDS-Katalogen werden Bilder für Zeilen angefordert, die im sichtbaren
Teil der Liste liegen; bereits gespeicherte Titelbilder werden aus dem Cache
verwendet. Ohne verfügbares Titelbild erscheint ein gewöhnliches Buchsymbol.
Fehlgeschlagene Bildabrufe werden für die laufende Sitzung vermerkt und nicht
in einer Schleife wiederholt. Nach einem Neustart und dem Öffnen des Katalogs
ist ein neuer Versuch möglich.

Beispiele für den Start im Terminal:

```sh
malferma-libro
malferma-libro "Buch mit Leerzeichen.epub" "Ein weiteres Buch.fb2"
malferma-libro -- -buch.txt
```

Anführungszeichen fassen einen Dateinamen mit Leerzeichen zu einem Argument
zusammen. Nach `--` gelten alle Argumente als Dateinamen. Eine Datei namens
`--version` löst dort beispielsweise keine Versionsausgabe aus. Der einzige
Startbefehl lautet `malferma-libro`.

## Das Hauptfenster

Die obere Leiste enthält das Öffnen von Büchern, die
Suche, den Vollbildmodus und das Hauptmenü. Im Lesebereich kommen
Inhaltsverzeichnis, Vor- und Zurücknavigation, Lesezeichen und
weitere Seitenwerkzeuge hinzu. Das kompakte Menü „Barrierefreiheit“ in der
oberen Leiste bündelt Vorlesen, dessen Sprache und Tempo sowie wichtige
Lesehilfen. Wenn Sie den Mauszeiger auf
einer Schaltfläche ruhen lassen, erscheint ein Hinweis. Befehle, die im
aktuellen Bereich nicht verfügbar sind, werden deaktiviert oder ausgeblendet.

Zusammengehörige Befehle sind gruppiert: Öffnen und Navigation befinden sich
links, Suche und Buchwerkzeuge näher an der Mitte. Tag-/Nacht- und
Vollbildmodus liegen nebeneinander, Barrierefreiheit und Hauptmenü am Rand.
Ein einziges Paar zum Vor- und Zurückblättern bleibt bei jeder Fensterbreite
in der Leiste. Das Inhaltsverzeichnis ist die einzige Kapitelliste. Die drei
Größenbefehle stehen im Menü „Barrierefreiheit“; ein zweites Größenmenü
entfällt. Die Seitenwerkzeuge erscheinen nur für PDF, DjVu und CBZ.
Tastenkombinationen und Mausgesten bleiben verfügbar.

Im ersten Abschnitt des Hauptmenüs öffnen Sie diese Bereiche:

- „Meine Bücher“ — importierte Bücher sowie die Suche nach Titel und Autor.
- „Lesen“ — das geöffnete Buch und die gespeicherte Leseposition.
- „Online-Bibliotheken“ — OPDS-Kataloge und das Herunterladen von Büchern.

Die Standardkürzel dafür sind Ctrl+1, Ctrl+2 und Ctrl+3. Die Schrift der Oberfläche
ist 15 % größer als die Systemschrift und folgt ihrer Schriftfamilie und
der Desktopskalierung. Die Buchschriftgröße wird getrennt eingestellt.

Das Fenster hat einen schmalen Rand und einen dezenten Schatten. Im maximierten
Fenster und im Vollbildmodus wird der äußere Rand ausgeblendet. Die Fenstergröße
lässt sich weiterhin durch Ziehen an den Rändern ändern; im Kontrastmodus bleibt
die Kontur deutlich sichtbar.

In der Mitte der Titelleiste stehen Buchtitel und Lesefortschritt.
Statusmeldungen erscheinen kurz über dem Fensterinhalt. Eine dauerhafte
untere Schaltflächenleiste gibt es nicht: Den größten Platz nimmt die
Buchseite ein.

## Weiterlesen und Ordnung in der Bibliothek

Die Karte „Weiterlesen“ im Bereich „Meine Bücher“ führt zum zuletzt
erfolgreich geöffneten Buch und seiner gespeicherten Position zurück. Das
bloße Hinzufügen einer Datei zur Bibliothek ersetzt dieses Buch nicht.
Solange noch kein Buch geöffnet wurde, wird die Karte nicht angezeigt.

Standardmäßig startet die Anwendung mit der Bibliothek. In den Einstellungen
können Sie „Beim Start das letzte Buch öffnen“ aktivieren. Eine ausdrücklich
übergebene Datei oder die Auswahl eines anderen Buches hat Vorrang vor
diesem automatischen Öffnen.

Filter und Sortierung befinden sich im aufklappbaren Menü der oberen
Bibliotheksleiste. Sie können alle Bücher oder die Status „Nicht begonnen“,
„Wird gelesen“ und „Gelesen“ anzeigen. Sortiert wird nach der letzten Öffnung,
nach Autor oder nach Titel. Bei „Zuletzt verwendet“ stehen bereits geöffnete
Bücher vor importierten Büchern, die noch nie geöffnet wurden. Die
Bibliothekssuche berücksichtigt Titel, Autor und Format.

Im Menü neben einem Buch können Sie seinen Lesestatus von Hand ändern.
Beim ersten Öffnen wird aus „Nicht begonnen“ der Status „Wird gelesen“.
Die Prozentangabe gibt die gespeicherte Position wieder. „Gelesen“ wird
manuell gesetzt: Das Erreichen des Buchendes ändert diesen Status nicht
automatisch.

## Lesen, Inhaltsverzeichnis und Suche

Wählen Sie ein Buch in der Bibliothek. Die Anwendung stellt Kapitel und
Leseposition wieder her. Die Position wird beim Lesen, beim Wechseln und
beim Schließen des Fensters automatisch gespeichert. EPUB, FB2, TXT,
HTML/XHTML und Markdown werden als Text gelesen; PDF, DjVu und CBZ werden
nach Dokumentseiten durchblättert.
Die Pfeilschaltflächen und Alt+← / Alt+→ wechseln zum vorherigen oder
nächsten Kapitel beziehungsweise zur vorherigen oder nächsten Seite.
Über den Anfang oder das Ende des Buches hinaus wird nicht gewechselt.

Am unteren Rand des Lesebereichs steht eine Seitenanzeige für das gesamte
Buch. Sie wird beim Scrollen mit Maus oder Tastatur und beim Wechseln über
Inhaltsverzeichnis, Suche oder Lesezeichen aktualisiert. Umfasst der sichtbare
Text mehrere Referenzseiten, erscheint ein Bereich wie „Seiten 12–13 von 640“.

EPUB, FB2, TXT, HTML/XHTML und Markdown verwenden durchgehende Referenzseiten:
Eine Seite umfasst 1800 Unicode-Zeichen einschließlich Leerzeichen und
Zeilenumbrüchen. Die Kapiteltexte werden unmittelbar hintereinander gezählt,
ohne leere Seiten oder Auffüllen am Kapitelende. Ein neues Kapitel kann auf
derselben Seite weitergehen. Schrift, Zeilenabstand und Fenstergröße ändern
weder die Seitennummern noch die Gesamtseitenzahl; der sichtbare Bereich kann
sich dabei ändern. Die Zahlen entsprechen keiner bestimmten Druckausgabe.
Der Hinweis zur Anzeige lautet „Referenzseiten des gesamten Buches“.

PDF und DjVu behalten ihre ursprünglichen Dokumentseiten; bei CBZ entspricht
jede berücksichtigte Bilddatei einer Seite. Ihre Nummerierung bleibt beim
Zoomen und beim Scrollen innerhalb des Bildes unverändert.

Öffnen Sie das Inhaltsverzeichnis über seine Schaltfläche in der oberen
Leiste oder mit F9. Wählen Sie den gewünschten Eintrag zum Wechseln.
In schmalen Fenstern legt sich die Seitenleiste über das Buch; dieselbe
Schaltfläche schließt sie wieder. In breiten Fenstern belegt sie nur einen
schmalen Bereich neben der Seite.

Die Seitenleiste erhält die Hierarchie von Kapiteln und Unterabschnitten;
Anmerkungen werden getrennt gruppiert. Ein EPUB-Inhaltsverzeichniseintrag
kann auf eine bestimmte Überschrift innerhalb eines Kapitels verweisen.
Bei seiner Auswahl wird zu dieser Stelle gescrollt, statt nur der Anfang
der Datei geöffnet. FB2-Anmerkungen bleiben erhalten und sind über das
Inhaltsverzeichnis erreichbar.

HTML/XHTML- und Markdown-Dateien werden jeweils als ein Textkapitel
eingelesen. Ihre Überschriften bilden ein hierarchisches Inhaltsverzeichnis;
die Einträge führen zur jeweiligen Stelle innerhalb dieses Kapitels.

Ctrl+F öffnet die Suche für den aktuellen Bereich:

- In der Bibliothek filtert sie Bücher nach Titel, Autor und Format.
- Beim Lesen durchsucht sie das gesamte Buch, einschließlich noch nicht
  geöffneter Kapitel. Die Ergebnisse zeigen Kapiteltitel und einen kurzen
  Textauszug.
- Bei PDF und DjVu werden die Textebenen der Seiten nacheinander durchsucht.
  Dafür werden keine Bilder sämtlicher Seiten erzeugt, und es findet keine
  Texterkennung per OCR statt. Ein Treffer wird im Bereich für den
  Seitentext angezeigt; er markiert keine Bildregion im Scan.
- CBZ-Bildseiten enthalten für die Anwendung keinen Text. Wortsuche und
  Vorlesen stehen dafür nicht zur Verfügung; OCR wird nicht ausgeführt.
- Im Katalog ist die Suche verfügbar, wenn der Katalog selbst eine
  unterstützte Suchvorlage bereitstellt.

Suche und zusätzliche Werkzeuge werden nur bei Bedarf geöffnet. Sie
verkleinern die Höhe des Lesebereichs daher nicht dauerhaft. Escape schließt
ein geöffnetes aufklappbares Menü.

Beim Eingeben des Suchbegriffs wird die Ergebnisliste gefüllt. Die
Leseposition ändert sich dadurch noch nicht. Wählen Sie ein Ergebnis oder
drücken Sie Enter, um zu einem Treffer zu wechseln. Shift+Enter und die
Schaltfläche für den vorherigen Treffer wechseln zurück. Die Schaltflächen
für den nächsten und vorherigen Treffer durchlaufen die Ergebnisse zyklisch.
Daneben befindet sich „Zur Position vor der Suche zurückkehren“: Diese
Schaltfläche stellt Kapitel oder Seite und die Position wieder her, an der
die Suche in diesem Buch begonnen hat.

Die Liste zeigt die ersten 200 Treffer. Gibt es weitere, fordert ein Hinweis
dazu auf, die Suche genauer einzugrenzen. Groß- und Kleinschreibung werden
nicht unterschieden. Auch bei Umwandlungen wie ß → ss werden die
ursprünglichen Zeichen korrekt markiert. Sie können die Suche mit ihrer
Abbruchschaltfläche oder in der Liste der laufenden Vorgänge abbrechen.
Falls der Text einzelner Seiten nicht gelesen werden konnte, weist die
Ergebnisliste darauf hin; verfügbare Treffer anderer Seiten bleiben sichtbar.
Scans ohne Textebene lassen sich betrachten, ihre Bildinhalte aber nicht
nach Wörtern durchsuchen.

## Textgröße und Darstellung

Die Tag-/Nacht-Schaltfläche in der oberen Leiste oder Ctrl+Shift+D schaltet
Fenster und Buchseite gemeinsam zwischen heller und dunkler Darstellung um.
Bei russischer Tastaturbelegung funktioniert auch Ctrl+Shift+В. Die Auswahl
wird gespeichert. Die Leseposition bleibt erhalten; pausiertes Vorlesen
wird nicht selbstständig fortgesetzt. Ursprüngliche Schriften und Farben
von PDF-/DjVu-Seiten und die ursprünglichen Bildfarben von CBZ bleiben
unverändert. Systemdarstellung und Sepia
sind weiterhin in den vollständigen Einstellungen verfügbar; die
Schaltfläche wählt ausdrücklich den Tag- oder Nachtmodus.

Im Menü „Barrierefreiheit“ der oberen Leseleiste stehen drei Größenbefehle
zur Verfügung: Text verkleinern, Standardgröße wiederherstellen und Text
vergrößern. Die Tastenkürzel lauten Ctrl+−, Ctrl+0 und Ctrl++. Bei Textbüchern beträgt die
Standardgröße 20; in den Einstellungen sind Werte von 12 bis 96 möglich.
Für PDF, DjVu und CBZ ändern dieselben Schaltflächen den Seitenzoom: Der
Standardwert ist 100 %, der verfügbare Bereich reicht von 25 bis 300 %.

Öffnen Sie „Einstellungen“ im Hauptmenü oder drücken Sie Ctrl+,.
Fensterdarstellung und Buchseite lassen sich getrennt anpassen:

- Das Fenster kann der Systemeinstellung folgen oder ausdrücklich hell
  beziehungsweise dunkel dargestellt werden.
- Symbolische Icons folgen dem Systemthema.
- Seitenhintergrund: wie im System, „Tag“, „Sepia“ oder „Nacht“.
- Buchschriftart: Systemschrift, Noto Serif, Noto Sans oder Liberation Serif.
  Mitgelieferte ergänzende Schriftarten helfen bei anderen Schriftsystemen.
- Maximale Textbreite: 480–2400 logische Pixel, standardmäßig 760.
  In breiten Fenstern steht die Textspalte mittig. In schmalen Fenstern wird
  sie an den verfügbaren Platz angepasst.
- Seitenhelligkeit: 30–100 %. Damit wird der Buchinhalt gedämpft, nicht die
  Hintergrundbeleuchtung des Monitors verändert. Andere Fenster und
  Systemeinstellungen bleiben unverändert.

Die Oberflächensprache wechselt unmittelbar nach der Auswahl in den
Einstellungen. Das geöffnete Buch und seine Leseposition bleiben erhalten.
Es stehen 49 Sprachen und Schriftvarianten zur Verfügung. Bei Sprachen,
die von rechts nach links geschrieben werden, wechselt die Richtung der
Bedienelemente. Die Absatzrichtung des Buches richtet sich unabhängig von
der Menüsprache nach seinem Text.

## Vollbildmodus und Monitore

Klicken Sie auf die Vollbildschaltfläche in der oberen Leiste oder drücken
Sie F11. Eine erneute Betätigung stellt das normale Fenster wieder her.
Escape schließt zuerst ein aufklappbares Menü oder bricht eine Mausgeste ab.
Ist beides nicht nötig, beendet die Taste den Vollbildmodus.

Beim Lesen im Vollbild wird die obere Leiste nach etwa zwei Sekunden ohne
Aktivität automatisch ausgeblendet. Um sie wieder einzublenden, bewegen
Sie den Mauszeiger in die oberen 24 logischen Pixel des Fensters, drücken
F10 oder wechseln mit Tab zur Leiste. Während Sie ihre Schaltflächen
mit sichtbarem Tastaturfokus bedienen oder ein Menü, Dialog beziehungsweise eine Geste aktiv ist, wird
die Leiste nicht ausgeblendet. Bei hohem Kontrast bleibt sie ebenfalls
sichtbar. Das automatische Ausblenden lässt sich in den Einstellungen
abschalten. Im normalen Fenster und in anderen Bereichen bleibt die Leiste
an ihrem Platz.

GTK berücksichtigt die Monitorskalierung. Beim Verschieben zwischen
Bildschirmen mit unterschiedlicher Skalierung bleibt Text in logischen
Einheiten bemessen; PDF-, DjVu- und CBZ-Seiten werden entsprechend der Pixeldichte
neu gerendert. Auf großen Bildschirmen können Sie die Spalte in den
Einstellungen verbreitern oder für angenehmes Lesen schmal lassen.
Globale Variablen wie GDK_SCALE müssen dafür nicht gesetzt werden.

Die Anwendung verarbeitet jeweils nur die angeforderte PDF-, DjVu- oder CBZ-Seite.
Das Raster ist auf 4096 Pixel an der längsten Kante und 12 MiPixels begrenzt.
Auf einem 8K-Bildschirm oder bei hohem Zoom kann das begrenzte Raster
vergrößert dargestellt werden: Die Seitengröße bleibt korrekt, die
Detailauflösung ist jedoch nicht unbegrenzt. Das Originaldokument wird
nicht verändert.

## Navigation mit Mausgesten

Halten Sie im Buchbereich die rechte Maustaste gedrückt und bewegen Sie
die Maus deutlich in horizontaler Richtung:

- Nach links — nächstes Kapitel oder nächste Seite.
- Nach rechts — vorheriges Kapitel oder vorherige Seite.

Der Wechsel erfolgt erst beim Loslassen, einmal pro Geste. Kurze,
überwiegend vertikale oder diagonale Bewegungen blättern nicht um.
Escape bricht die aktuelle Geste ab. Bei eingeschalteten Gesten öffnet ein
kurzer Rechtsklick das Menü zum Kopieren und Auswählen von Text. Wenn
Gesten ausgeschaltet sind, bleibt das übliche Kontextmenü des Textwidgets
erhalten.

Sie können Gesten unter „Barrierefreiheit“ in den Einstellungen
abschalten. Die Navigationsschaltflächen und Alt+← / Alt+→ funktionieren
unabhängig davon.

## Barrierefreiheit

Öffnen Sie das kompakte Menü „Barrierefreiheit“ über seine Schaltfläche in
der oberen Leiste oder mit Ctrl+Shift+A. Bei kyrillischer Tastaturbelegung
funktioniert auch Ctrl+Shift+Ф. Das Tastenkürzel öffnet das Menü auch bei
ausgeblendeter oberer Leiste.

Das Menü enthält Vorlesen, Pause, Fortsetzen und Stopp sowie die Auswahl
von Vorlesesprache und „Sprechtempo (%)“. Es bietet außerdem Textgröße verkleinern,
zurücksetzen und vergrößern, hohen Kontrast, Fettdruck, Zeilenabstand und
die Voreinstellung für Menschen mit Sehschwäche. Die entsprechenden
Darstellungseinstellungen bleiben auch im Einstellungsfenster verfügbar.
Die Auswahl der Vorlesesprache und die Textgrößenbefehle stehen unter ihren
Beschriftungen. Die Bildlaufleiste hat neben dem Inhalt einen eigenen Platz.
Die Menühöhe passt sich dem Fenster an; weiter unten liegende Werkzeuge
erreichen Sie durch Scrollen.

Unter „Barrierefreiheit“ in den Einstellungen finden Sie weiterhin „Hoher Kontrast“,
„Fetter Text“, einen Zeilenabstand von 1,0–2,0 und einen „Modus für Menschen
mit Sehschwäche“. Diese Voreinstellung setzt die Textgröße auf 32, verwendet
Noto Sans und Fettdruck, aktiviert hohen Kontrast und stellt den
Zeilenabstand auf 1,5 sowie die Spaltenbreite auf 1000. Bei geöffneten
PDF-, DjVu- oder CBZ-Dokumenten wird der Zoom auf mindestens 150 % erhöht.
Anschließend können Sie jede Einstellung einzeln ändern.

Schrift- und Zeilenabstandseinstellungen verändern Textbücher und den
extrahierten Seitentext. Sie setzen die Schrift in PDF-/DjVu-Scans nicht
neu. Vergrößern Sie einen Scan stattdessen über den Zoom. Hoher Kontrast
wirkt auf den Text; das Originalbild wird weder in Text umgewandelt noch
per OCR erkannt.
Auch CBZ-Bildseiten werden über den Zoom vergrößert; Schriftwahl und
Zeilenabstand verändern die in den Bildern enthaltenen Buchstaben nicht.

Im kompakten Menü können Sie außerdem die Lupe für den Lesebereich
einschalten und unter „Vergrößerungsfaktor“ einen Wert von 2–4× wählen.
Sie vergrößert einen Ausschnitt des Buchinhalts, ohne Schriftgröße,
Zeilenumbrüche oder das Layout einer PDF-, DjVu- oder CBZ-Seite zu ändern.
Beim Einschalten zeigt sie die Mitte des Lesebereichs vergrößert.
Innerhalb des Lesebereichs folgt sie
dem Mauszeiger; außerhalb davon wird wieder die Mitte vergrößert.
Damit ist sie auch ohne Mausbewegung nutzbar. Die Aktivierung gilt nur
für die laufende Sitzung und wird beim nächsten Start nicht übernommen.

Tab und Shift+Tab verschieben den Fokus zwischen erreichbaren Elementen;
Enter oder die Leertaste aktiviert die ausgewählte Schaltfläche.
Schaltflächen haben Textbezeichnungen für die Barrierefreiheitsfunktionen
von GTK. Die Zusammenarbeit mit einer bestimmten Orca-Konfiguration und
Arbeitsumgebung hängt von der installierten AT-SPI-Infrastruktur ab.
Die Vorlesefunktion mit Piper ersetzt keinen systemweiten Screenreader.

## Vorlesen

Die Vorlesefunktion verwendet ausschließlich Piper und arbeitet lokal,
sobald die Laufzeitumgebung und das gewünschte Sprachmodell installiert
sind. Buchtext wird nicht ins Internet übertragen. Die Modelle gehören
nicht zum Anwendungspaket und werden auf Ihren ausdrücklichen Wunsch
separat heruntergeladen. Der Katalog bietet nur Modelle mit geprüfter
freier Lizenz an.

Installieren Sie Piper in einer eigenen Python-Umgebung im Benutzerkonto,
statt `sudo pip` mit dem systemweiten Python zu verwenden.
Für die Audioausgabe benötigen Sie `paplay` aus `pulseaudio-utils` oder
`aplay` aus `alsa-utils`. Eine übliche Einrichtung mit PulseAudio oder PipeWire:

```sh
sudo apt install python3-venv pulseaudio-utils
piper_env="${XDG_DATA_HOME:-$HOME/.local/share}/malferma-libro/piper"
python3 -m venv "$piper_env"
"$piper_env/bin/python" -m pip install "piper-tts==1.8.0"
```

Beim üblichen Datenpfad findet die Anwendung diese Umgebung automatisch.
Wenn XDG_DATA_HOME gesetzt ist, muss der Pfad absolut sein.
Mit `PIPER_PYTHON` lässt sich ausdrücklich ein anderer Python-Interpreter
mit installiertem Piper auswählen.
Änderungen an `PIPER_PYTHON` gelten beim nächsten Anwendungsstart.
Sprachmodelle werden ohne Neustart verfügbar.

Unterstützt werden Russisch, Ukrainisch, Englisch, Deutsch, Französisch,
Spanisch, Italienisch und Portugiesisch. Die ausgewählte Sprache benötigt
ein kompatibles installiertes Piper-Modell. Der geprüfte Downloadkatalog
enthält Stimmen für Englisch, Ukrainisch, Deutsch, Französisch, Spanisch
und Italienisch. Für Russisch und Portugiesisch muss derzeit ein lokales
Modell hinzugefügt werden. Die Anwendung bestätigt nicht die Lizenz einer
selbst ausgewählten Datei.

Öffnen Sie „Einstellungen“ → „Vorlesen“ oder „Piper-Stimmen“ im Menü
„Barrierefreiheit“ und wählen Sie Sprache und Stimme.
Die Stimmenliste wird nach Sprache gefiltert. Die Auswahl einer bestimmten
Stimme stellt deren Sprache ein; ein Wechsel zu einer unvereinbaren Sprache
setzt die Stimmenwahl auf automatisch zurück. Ein Katalogmodell wird erst
heruntergeladen, wenn Sie die Download-Schaltfläche betätigen. Fortschritt
und Abbruch finden Sie in der Liste laufender Vorgänge; die Stimme ist nach
Abschluss verfügbar. Um eine lokale Stimme hinzuzufügen, verwenden Sie die
entsprechende Schaltfläche und wählen Sie deren `.onnx`-Datei; die passende
`.onnx.json`-Datei muss daneben liegen. Prüfen Sie die Lizenz und Ihre
Nutzungsberechtigung für ein lokales Modell gesondert.

Mit der Hörprobe wird offline ein kurzer Beispieltext mit der gewählten
Stimme vorgelesen. Laufendes Vorlesen eines Buchs wird pausiert und bleibt
pausiert. Die Schaltfläche zur Piper-Installationsanleitung öffnet dieses
Handbuch. Heruntergeladene Modelle liegen unter `voices/` im Datenverzeichnis.

Wählen Sie im Menü „Barrierefreiheit“ die Sprache und unter „Sprechtempo (%)“
einen Wert von 44–250 %. Dieselben Einstellungen finden Sie auch im
Einstellungsfenster. Die Auswahl
„Anhand des Kapiteltexts erkennen“ versucht, eine dieser acht Sprachen zu
erkennen. Bei kurzem oder mehrdeutigem Text sollten Sie die Sprache
manuell festlegen. Für andere Sprachen wird keine Vorleseunterstützung
zugesagt; dies schränkt weder Oberflächenübersetzungen noch die Anzeige
von Büchern ein.
100 % entspricht dem normalen Tempo des Modells. Die Prozentangabe bestimmt
die relative Synthesegeschwindigkeit; die tatsächliche Wortzahl pro Minute
hängt vom Modell und vom Text ab.

Die Vorleseschaltfläche im Menü „Barrierefreiheit“ beginnt an der aktuellen
Lesestelle, pausiert und setzt das Vorlesen fort. Während einer Pause lautet
die Statusmeldung „Vorlesen pausiert“; mit „Fortsetzen“ geht es an derselben
Stelle weiter. Dasselbe gilt für die
Leertaste, wenn der Fokus im Lesebereich und nicht in einem Eingabefeld
oder auf einer Schaltfläche liegt. Zum Beenden verwenden Sie
„Stopp“ im selben Menü oder Ctrl+Shift+S. Beim Verlassen des Bereichs „Lesen“
wird das Vorlesen pausiert. Bei einem manuellen Kapitelwechsel wird das
bisherige Vorlesen beendet.

Für PDF und DjVu verwendet die Vorlesefunktion die Textebene der aktuellen
Seite. Besteht die Seite nur aus einem Bild, lässt sie sich anzeigen,
aber Textsuche und Vorlesen stehen dafür nicht zur Verfügung.
Eine automatische Texterkennung findet nicht statt.
CBZ besteht aus Bildseiten ohne Textebene; diese Seiten können nicht
vorgelesen oder nach Wörtern durchsucht werden.

## Lesezeichen

Öffnen Sie das Lesezeichenmenü in der oberen Leiste und wählen Sie das
Hinzufügen eines Lesezeichens. Alternativ drücken Sie bei geöffnetem Buch
im Bereich „Lesen“ Ctrl+B. Ein Lesezeichen speichert das aktuelle Kapitel
oder die aktuelle Seite und die Position. Wählen Sie es im selben Menü,
um dorthin zurückzukehren. Bei Textbüchern werden Kapiteltitel und ein
lesbarer Auszug nahe der Lesestelle angezeigt. Bei PDF/DjVu sehen Sie die
Seitennummer, beginnend mit 1, und den ausgewählten Text. Ohne Auswahl wird
der Anfang der Textebene dieser Seite verwendet. Bei einem Scan ohne
Text bleibt die Beschriftung mit der Seitennummer.
Bei CBZ enthält das Lesezeichen die Seitennummer und die Bildlaufposition,
ohne Textauszug. Die gespeicherte Position in PDF, DjVu und CBZ bezieht sich
auf den Bildlauf, nicht auf eine
Zeichennummer im Text.

Die Notizschaltfläche neben einem Lesezeichen öffnet einen Editor für bis
zu 2000 Zeichen. Ein Zähler zeigt die Länge; oberhalb der Grenze ist das
Speichern nicht möglich. Gespeichert wird nur die Notiz dieses
Lesezeichens; leerer Text entfernt die Notiz. Wurde das Lesezeichen
inzwischen gelöscht oder ein anderes Buch geöffnet, wendet der Editor
die Änderungen nicht auf einen anderen Eintrag an. Die Löschschaltfläche
neben dem Lesezeichen entfernt ausschließlich dieses Lesezeichen.

Lesezeichen und letzte Leseposition bleiben lokal gespeichert.
Wenn Sie die Originaldatei nach dem Import löschen, bleiben die
Bibliothekskopie und ihre Lesezeichen erhalten.

## OPDS-Online-Bibliotheken

Öffnen Sie „Online-Bibliotheken“ und anschließend die Verbindungsschaltfläche
in der oberen Leiste. Klicken Sie auf „+“ und geben Sie einen Namen sowie
die vollständige URL eines öffentlichen OPDS-1.x-Katalogs an, zum Beispiel
eines Calibre-Katalogs im Heimnetz. Wählen Sie den Katalog und klicken Sie
auf „Verbinden“.

Öffnen Sie Katalogbereiche, nutzen Sie eine angebotene Suche und wechseln
Sie mit den Navigationsschaltflächen zwischen Katalogseiten. Wählen Sie
eine passende Downloadvariante des Buches. Nach dem Herunterladen wird
es in Ihre persönliche Bibliothek importiert und ist ohne Verbindung zum
Katalog verfügbar.
Direkte Downloads werden für EPUB, FB2, TXT, PDF, DjVu, HTML/XHTML,
Markdown und CBZ unterstützt.

Mit „−“ entfernen Sie einen Katalog aus der Verbindungsliste.
Bereits importierte Bücher bleiben erhalten. Unterstützt werden HTTP
und HTTPS ohne Passwort in der Adresse. Kataloge mit Anmeldung, OPDS 2
und DRM werden nicht unterstützt.

## Hintergrundvorgänge, Abbrechen und Fehler

Öffnen, Importieren, Herunterladen, die Suche im gesamten Buch und die
Seitenaufbereitung laufen im Hintergrund. Die Schaltfläche „Laufende
Vorgänge“ in der oberen Leiste zeigt aktive Aufgaben, verfügbaren
Fortschritt und Abbruchschaltflächen. Nicht in jeder Phase ist ein
genauer Prozentwert bekannt; teilweise erscheint eine Warteanzeige.

Ein Abbruch verhindert weitere Schritte, sobald dies sicher möglich ist.
Eine bereits laufende Netzwerkanfrage oder ein externer Verarbeitungsschritt
kann später enden. Ein Abbruch unterbricht nicht jeden Systemaufruf sofort.
Bereits importierte Bücher und andere schon gespeicherte Änderungen
bleiben in der Bibliothek. Ein abgebrochenes oder überholtes Ergebnis
soll das aktuell geöffnete Buch nicht wechseln.

Fehlermeldungen erläutern Vorgang und Ursache. Wo möglich startet
„Erneut versuchen“ den Vorgang erneut. Fehlt eine Datei, können Sie
„Buch auswählen…“ verwenden und eine erreichbare Kopie angeben.
Prüfen Sie bei Netzwerkfehlern Verbindung und Katalogadresse, bei
Zugriffsfehlern die Berechtigungen und die Erreichbarkeit des Datenträgers.

## Tastaturbefehle

Um die Tastenbelegung zu ändern, öffnen Sie „Einstellungen“ →
„Tastenkombinationen“. Wählen Sie unter „Modus“ zwischen „Standard“ und
„Benutzerdefiniert“. Das benutzerdefinierte Profil übernimmt alle
Standardbelegungen, die Sie nicht geändert haben.

1. Wählen Sie neben einer Aktion „Tastenkombination ändern“.
2. Drücken Sie im Dialog die neue Tastenkombination. „Deaktivieren“ entfernt
   die Tastenbelegung dieser Aktion; „Standard“ stellt ihre ursprünglichen
   Tasten wieder her.
3. Mit „Speichern“ wird die Änderung sofort wirksam und für spätere Starts
   gespeichert. „Abbrechen“ oder Escape schließt den Dialog ohne Änderungen.

Eine neue Belegung ersetzt auch die bisherigen Varianten der Standardtasten
für die russische Tastaturbelegung. Bereits belegte Kombinationen werden
abgewiesen; dabei werden auch lateinische und kyrillische Zeichen auf
derselben physischen Taste berücksichtigt. Escape, Tab, die üblichen
Bearbeitungsbefehle Ctrl+C/V/X/A/Z/Y, normale Texteingaben und Navigationstasten
ohne Zusatztaste bleiben reserviert. Verwenden Sie Strg (Ctrl), Alt oder eine
Funktionstaste; Kombinationen mit Super werden nicht unterstützt. Die
Leertaste allein ist nur für das Vorlesen zulässig und wirkt bei Fokus
im Lesebereich.

Ein Wechsel des „Modus“ gilt sofort. Beim Zurückwechseln zu „Standard“ bleibt
das benutzerdefinierte Profil für eine spätere Aktivierung gespeichert.
„Alle Tastenkombinationen zurücksetzen“ löscht dagegen sofort alle eigenen
Belegungen und aktiviert das Standardprofil. Andere Einstellungen bleiben
erhalten. „Tastenkombinationen“ im Hauptmenü zeigt die tatsächlich aktive
Belegung. Die folgende Tabelle beschreibt die Standardtasten; normale
GTK-Befehle wie Escape sind vom Profil unabhängig.

Die folgenden Befehle gelten im Hauptfenster. Offene Dialoge und Eingabefelder
behalten das gewohnte GTK-Verhalten bei. Lesebefehle, einschließlich des
Hinzufügens von Lesezeichen und des Beendens der Vorlesefunktion, erfordern
den aktiven Bereich „Lesen“ und ein geöffnetes Buch. Ctrl entspricht der
Strg-Taste, Shift der Umschalttaste.

| Tastenkürzel | Aktion |
| --- | --- |
| Ctrl+O | Ein oder mehrere Bücher öffnen |
| Ctrl+F | Suche im aktuellen Bereich |
| Ctrl+, | Einstellungen |
| Ctrl+Shift+A | Barrierefreiheit öffnen; bei kyrillischer Belegung auch Ctrl+Shift+Ф |
| Ctrl+Shift+D | Zwischen Tag- und Nachtmodus wechseln |
| Ctrl+1 | Meine Bücher |
| Ctrl+2 | Lesen |
| Ctrl+3 | Online-Bibliotheken |
| Ctrl+B | Lesezeichen im geöffneten Buch hinzufügen |
| Ctrl+− / Ctrl++ | Textgröße oder PDF-/DjVu-/CBZ-Zoom verkleinern / vergrößern |
| Ctrl+0 | Standardtextgröße oder Zoom von 100 % |
| Alt+← / Alt+→ | Vorheriges / nächstes Kapitel oder vorherige / nächste Seite |
| F9 | Inhaltsverzeichnis ein- oder ausblenden |
| F11 | Vollbildmodus ein- oder ausschalten |
| F10 | Ausgeblendete obere Leiste zeigen und ihre Schaltflächen fokussieren |
| Escape | Menü schließen, Geste abbrechen oder Vollbildmodus verlassen |
| Leertaste | Vorlesen / pausieren / fortsetzen bei Fokus im Lesebereich |
| Ctrl+Shift+S | Vorlesen beenden |
| F1 | Dieses Handbuch öffnen |
| Ctrl+? (Ctrl+Shift+/) | Tastaturbefehle anzeigen |
| Ctrl+Q | Hauptfenster schließen |

Beim Öffnen eines Buches erhält der Lesebereich den Fokus; Sie können sofort
mit der Tastatur scrollen. Klicken Sie nach dem Bedienen anderer Elemente auf
den Text oder das Seitenbild, um zum Lesen zurückzukehren. Schaltflächen der
Leiste, Inhaltsverzeichnis, Suchfeld, Textebene des Dokuments, andere
Eingabefelder sowie offene Menüs und Dialoge behalten ihre gewohnte
Tastenbedienung.

| Lesetasten | Aktion |
| --- | --- |
| ↑ / ↓ | Ein kleines Stück nach oben / unten scrollen |
| ← / → | Vorherige / nächste Seite: in Textbüchern um 90 % der sichtbaren Höhe; in PDF/DjVu/CBZ zur benachbarten Dokumentseite |
| Page Up / Page Down (Bild ↑ / Bild ↓) | Um 90 % der sichtbaren Höhe scrollen; am bereits erreichten Rand zum vorherigen / nächsten Kapitel oder zur vorherigen / nächsten Dokumentseite wechseln |
| Home / End (Pos1 / Ende) | Anfang / Ende des aktuellen Kapitels oder der aktuellen Dokumentseite |
| Ctrl+Home / Ctrl+End (Strg+Pos1 / Strg+Ende) | Anfang / Ende des gesamten Buches |

← / → lassen in Textbüchern 10 % Überlappung; am bereits erreichten Rand
öffnen sie das Ende des vorherigen oder den Anfang des nächsten Kapitels.
In PDF, DjVu und CBZ öffnen sie sofort die benachbarte Seite an deren Anfang,
auch wenn die aktuelle Seite vergrößert und gescrollt ist. Die Richtung bleibt
bei LTR- und RTL-Büchern gleich: ← zurück, → vorwärts. Die Seitennummern
laufen weiterhin durch das gesamte Buch.
↑ / ↓ wechseln kein Kapitel. Alt+← / Alt+→ wechseln direkt zum benachbarten
Kapitel oder zur benachbarten Seite. Page Up öffnet das Ende des vorherigen
Kapitels oder der vorherigen Seite, Page Down den Anfang des nächsten
Kapitels oder der nächsten Seite. Am Anfang und Ende des Buches endet
die Navigation. Eine eigene Belegung einer Ctrl-Kombination hat Vorrang
vor dem Bildlauf. Varianten mit Shift behalten die normale Textauswahl
von GTK bei; Ctrl+C kopiert ausgewählten Text, soweit das jeweilige Widget
dies unterstützt. Im Buchsuchfeld wechselt Enter zum nächsten Treffer,
Shift+Enter zum vorherigen.
Die Navigationstasten des Ziffernblocks funktionieren bei ausgeschaltetem
Num Lock; bei eingeschaltetem Num Lock bleiben Ziffern normale Ziffern.
Diese Lesebefehle erscheinen auch in der Tastenkürzelübersicht. Eine durch
eine eigene Belegung ersetzte Ctrl-Kombination wird dort nicht mehr als
Bildlaufbefehl angezeigt.

## Hilfe im Terminal

```sh
malferma-libro --help
malferma-libro --manual
malferma-libro --manual=de
malferma-libro --license
malferma-libro --version
man malferma-libro
```

`man` wird vom optionalen Paket `man-db` bereitgestellt. Falls der Befehl
nicht gefunden wird, installieren Sie es mit `sudo apt install man-db`
oder verwenden Sie `--manual` beziehungsweise die eingebaute Hilfe:
Beide kommen ohne `man-db` aus.

Die Informationsbefehle `--help`, `--manual`, `--license` und `--version`
benötigen weder GTK noch eine laufende grafische Sitzung, ein Audiogerät
oder Netzwerkzugriff. `-h` bedeutet dasselbe wie `--help`.
Die Kurzhilfe ist auf Russisch, Englisch, Deutsch und Ukrainisch verfügbar.
Handbücher werden für diese vier Sprachen vollständig mitgeliefert.
Bei anderen Sprachumgebungen dient Englisch als Ausweichsprache.
`--manual` wählt automatisch, `--manual=ru|en|de|uk` beschreibt die vier
ausdrücklichen Varianten: Verwenden Sie jeweils genau einen Sprachcode,
zum Beispiel `--manual=de`. Die Sprache kann auch im Handbuchfenster
ausgewählt werden; „Automatisch“ folgt dort der aktuellen Oberflächensprache.
`--license` gibt den vollständigen Originaltext der GNU GPL v3 aus,
keine Zusammenfassung.

GTK 4 wählt die grafische Sitzung anhand der Systemumgebung, darunter
DISPLAY und WAYLAND_DISPLAY. Unbekannte Optionen werden mit Status 2
abgewiesen. Informationsbefehle öffnen keine mitgegebenen Bücher.
Status 0 bedeutet Erfolg, Status 1 einen fehlgeschlagenen Start oder eine
nicht lesbare erforderliche Ressource. Pro Aufruf kann nur einer der
Informationsmodi gewählt werden.

## Speicherort der Daten und Sicherungskopien

Neue Installationen speichern Daten unter `~/.local/share/malferma-libro/`
oder, bei absolut gesetztem XDG_DATA_HOME, unter
`$XDG_DATA_HOME/malferma-libro/`.
Bücher werden nicht automatisch verschoben oder gelöscht.

Das Verzeichnis enthält `library.json` mit Bibliothek, Einstellungen,
Lesestatus, zuletzt geöffnetem Buch, Lesezeichen, Notizen und Lesepositionen,
die Sicherung `library.json.bak`, das Unterverzeichnis `books/` mit den
verwalteten Buchkopien, den lokalen Titelbild-Cache `covers/`, Piper-Modelle
unter `voices/` und das Zwischenverzeichnis `downloads/` für Downloads.

Für eine vollständige Sicherung schließen Sie die Anwendung und kopieren
das gesamte Datenverzeichnis. Schließen Sie die Anwendung auch vor einer
Wiederherstellung. Ersetzen Sie nicht nur eine JSON-Datei ohne die
dazugehörigen Bücher: Die Einträge verweisen auf lokale Kopien.
Die Anwendung kann beschädigte Metadaten aus der Sicherung wiederherstellen
und bewahrt die beschädigte Datei zur Untersuchung gesondert auf.
Meldet sie ein neueres Datenschema, verwenden Sie eine dazu kompatible
Anwendungsversion.

Das Entfernen des Pakets mit APT löscht Ihre persönliche Bibliothek im
Benutzerverzeichnis nicht. Eine Synchronisierung zwischen Geräten und
Cloud-Speicherung sind nicht implementiert.

## Formatgrenzen und Fehlerbehebung

EPUB und FB2 werden in Textkapitel mit Abbildungen umgewandelt. Bilder passen
sich der Breite des Lesebereichs an. Klicken Sie auf ein Bild, um es in einem
eigenen Fenster zu öffnen. Mit „Vergrößern“, „Verkleinern“ und „An Fenster
anpassen“ ändern Sie seine Größe. Dieselben Funktionen sind über die Tasten
+, − und 0 erreichbar. Escape schließt die Ansicht und führt zum
Buch zurück. Abbildungen verändern nicht den Text, auf dem Suche, Vorlesen,
Lesezeichen und die Seitenzählung des gesamten Buches beruhen.

EPUB unterstützt lokale PNG- und JPEG-Bilder, auch Rasterbilder innerhalb
von SVG-Hüllen. FB2 und FB2.ZIP unterstützen eingebettete Bilder aus
binary-Blöcken. Für WebP wird ein geeigneter installierter GdkPixbuf-Lader
benötigt. SVG-Vektorgrafiken, externe Bilder, ursprüngliche CSS-Stile,
interaktive Elemente und das genaue Layout werden nicht nachgebildet.
Beim Lesen werden keine Bilder aus dem Internet geladen. Fehlende,
beschädigte, nicht unterstützte oder zu große Abbildungen verhindern
nicht das Lesen des Textes.

Jede Abbildung ist auf 8 MiB begrenzt; beim Einlesen eines Buches werden
höchstens 32 MiB kodierte Bilddaten gespeichert. Es werden bis zu 512 verschiedene Bilder
und 2048 Bildverweise verarbeitet. Titelbilder für die Bibliothek werden
gesondert aufbereitet.

TXT, HTML/XHTML und Markdown werden als Text dargestellt; das ursprüngliche
Webseitenlayout und CSS werden nicht nachgebildet. Markdown wird nach
CommonMark eingelesen, ohne Erweiterungen für GFM-Tabellen oder Fußnoten.
In Markdown enthaltenes rohes HTML bleibt wörtlicher Text. Bilder liefern
nur ihren Alternativtext, Links ihre Beschriftung; eingerückte und mit
Codezäunen markierte Codeblöcke bleiben als Text erhalten. JavaScript,
externe Bilder und Netzwerkressourcen werden nicht ausgeführt oder geladen.
HTML-/Markdown-Quelldateien dürfen bis zu 64 MiB groß sein; der dekodierte
Text ist auf 32 × 1024 × 1024 Zeichen begrenzt. Auch kleinere Dateien können
bei zu großer Verschachtelung oder Komplexität abgewiesen werden.

Für HTML/XHTML und Markdown wird UTF-8 empfohlen. Eine Byte-Reihenfolge-Markierung
erkennt UTF-8, UTF-16 und UTF-32. HTML kann außerdem unterstützte
Textkodierungen in XML- oder Meta-Angaben deklarieren. Ohne solche Angaben
wird zuerst UTF-8 und danach Windows-1251 versucht.

PDF und DjVu bewahren das Seitenbild und die Anordnung seiner Elemente.
CBZ zeigt seine Bildseiten mit erhaltenem Seitenverhältnis. DRM-geschützte Bücher
werden nicht unterstützt. Die Eingabe eines Passworts für geschützte PDFs
ist in der grafischen Oberfläche noch nicht vorgesehen. DjVu unterstützt
eigenständige Dateien und gebündelte Bücher; externe Teildateien müssen
vorher zu einer Datei zusammengefasst werden.

Prüfen Sie bei Fehlern beim Öffnen das Format, die Zugriffsrechte und die
Meldung der Anwendung. Für PDF wird `poppler-utils` benötigt, für DjVu
`djvulibre-bin`, für Markdown `python3-markdown-it` (mindestens Version 3.0.0).
Installieren Sie dieses Debian-Paket auch beim Start aus dem Quellcode.
PDF-/DjVu-Quelldateien sind auf 64 MiB und 10 000 Seiten
begrenzt. Diese Grenzen schützen die Ressourcen der Anwendung und
verändern das Originalbuch nicht.

CBZ-Archive sind auf 512 MiB Quelldateigröße, 1 GiB entpackten Inhalt,
20 000 ZIP-Einträge und 10 000 Bildseiten begrenzt. PNG und JPEG werden
unterstützt; WebP benötigt einen installierten GdkPixbuf-Lader für dieses
Format. SVG wird nicht als Bildseite geöffnet. Jede Quellbilddatei darf
höchstens 32 MiB groß sein, höchstens 16 384 Pixel je Bildkante und
insgesamt 32 MiPixels enthalten. Die gerenderte Seite bleibt auf 4096 Pixel
an der längsten Kante und 12 MiPixels begrenzt.

Die Seitenreihenfolge folgt den Pfaden und Dateinamen mit natürlicher
Zahlensortierung: beispielsweise kommt Seite 2 vor Seite 10. Versteckte
Einträge und Inhalte von __MACOSX werden ignoriert. Wenn eine geeignete
ComicInfo.xml enthalten ist, können daraus Titel und Autor übernommen
werden. Für das Titelbild werden höchstens die ersten 32 geordneten
Bildseiten geprüft. Die erste gültig dekodierbare Seite wird auf höchstens
1024 Pixel je Kante verkleinert und als PNG vorbereitet. Spätere Bildseiten
bleiben unabhängig von dieser Titelbildsuche lesbar. Die Grenze von 4 MiB
für Titelbilder begrenzt nicht die CBZ-Quellseite; für diese gelten die
gesonderten Quellbildgrenzen oben. CBZ liefert keinen
Seitentext für Suche oder Vorlesen und verwendet kein OCR.

Für Titelbilder werden PNG und JPEG bis zu 4 MiB unterstützt, mit höchstens
4096 Pixeln je Bildkante und insgesamt höchstens 4 MiPixels. Nicht unterstützte,
zu große oder beschädigte Bilder werden übersprungen; das Buch bleibt verfügbar.

Falls die Oberfläche nicht startet, benötigen Sie unter Debian 13 oder Ubuntu 24.04
`python3-gi`, `gir1.2-gtk-4.0` und `gir1.2-adw-1`; für das Vektorlogo wird
`librsvg2-common` benötigt. Verwenden Sie beim
Start aus dem Quellcode das systemeigene `/usr/bin/python3`; Kurzhilfe und
Handbuch sind auch ohne diese grafischen Abhängigkeiten verfügbar.
Wenn das Vorlesen nicht funktioniert, prüfen Sie Piper in der ausgewählten
Python-Umgebung, das installierte Modell für die gewünschte Sprache und
`paplay` oder `aplay`. Falls die Suche in PDF/DjVu fehlt, prüfen Sie, ob eine
Textebene vorhanden ist. Falls OPDS nicht geöffnet werden kann, prüfen
Sie Netzwerk und URL: Benötigt wird eine OPDS-1.x-Adresse, nicht die
gewöhnliche Webseite einer Bibliothek.

## Lizenzen und Programminformationen

Der Quellcode steht unter GPL-3.0-or-later. Der vollständige Text der
GNU GPL v3 wird als LICENSE mitgeliefert und ist mit
`malferma-libro --license` verfügbar. Das Fenster mit den
Programminformationen zeigt den üblichen GPL-Hinweis. Die Erlaubnis,
eine spätere GPL-Version zu verwenden, ist in den Lizenzmetadaten
des Projekts festgehalten.

Logo und abgeleitete Symbole stehen mit Bestätigung des Projektinhabers
unter GPL-3.0-or-later; die Erlaubnis ist in LOGO_LICENSE.md dokumentiert.
Für die Schriftarten gilt weiterhin SIL OFL 1.1. Lizenztexte und
Namensnennungen stehen in FONT_LICENSES.md und den Schriftdateien.
AppStream-Metadaten stehen unter CC0-1.0. Herkunft der Ressourcen und
die Lizenzprüfung sind in LICENSE_AUDIT.md beschrieben.
Piper und Sprachmodelle behalten ihre eigenen Lizenzen. Quellen und
Modellbedingungen stehen in PIPER_LICENSES.md; die Anwendungslizenz
ändert die Lizenzen einzelner Modelle nicht.
Systembibliotheken Dritter behalten ihre eigenen Lizenzen. Das Programm
wird im Rahmen der GPL ohne Gewährleistung bereitgestellt.

Dieses Handbuch wird unter GPL-3.0-or-later verbreitet.
