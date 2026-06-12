# ZIELBILD — DeckForge

**PowerPoint-Automatisierung in Consulting-Qualität. Komplett selbst gebaut. Null externe Abhängigkeiten.**

Stand: 12. Juni 2026 · Eigentümer: Pano Goutzeris (ROOTS Brand Strategy Consultants GmbH)

---

## 1. Vision

DeckForge ist eine eigenentwickelte PowerPoint-Engine, die jede bestehende `.pptx`-Datei
(insbesondere Firmen-Master und Templates) vollständig einlesen, ihr Design verstehen und
auf dieser Basis **beliebig viele neue Folien in exakt demselben Design** erzeugen kann —
programmatisch, reproduzierbar und ohne dass PowerPoint dafür geöffnet werden muss.

Das Endziel: Der komplette Foliebau-Prozess einer Beratung — vom Inhalt (Stichpunkte,
Zahlen, Strukturen) zur fertigen, CI-konformen Folie — ist automatisiert. Was heute
Stunden manueller Formatierungsarbeit kostet, wird zu einem Funktionsaufruf oder einem
JSON-Dokument.

## 2. Ausgangslage & Problem

- Foliebau ist in der Beratung einer der größten manuellen Zeitfresser: Layouts nachbauen,
  Farben treffen, Abstände pixeln, Tabellen formatieren, Master-Vorgaben einhalten.
- Bestehende Bibliotheken (python-pptx etc.) sind generisch, decken Consulting-Bausteine
  (Harvey Balls, Wasserfälle, Agenden, Statusmatrizen) nicht ab und sind eine externe
  Abhängigkeit, die man weder versteht noch kontrolliert.
- Templates/Master existieren bereits — aber niemand kann sie heute maschinell „lesen“
  und als Designsystem wiederverwenden.

**Kernanforderung:** Eine individuelle, vollständig selbst geschriebene Codelösung,
exakt zugeschnitten auf den eigenen Use Case — jede Zeile verstehbar, erweiterbar, ohne
Lizenz- oder Versionsrisiken Dritter.

## 3. Zielbild im Detail

### 3.1 Template-Analyse (Parser)

DeckForge öffnet jede valide `.pptx`-Datei und extrahiert ihre komplette Designstruktur:

- **Paket-Ebene:** ZIP-Container, Content Types, Relationships, alle Parts (OPC-Standard).
- **Theme:** Farbschema (dk1/lt1/dk2/lt2, accent1–6, hlink), Schriftschema (Major/Minor
  Font), Formatschema.
- **Slide Master:** Farb-Mapping (clrMap), Textstil-Hierarchien (Titel-, Body-, Other-Styles
  über alle 9 Gliederungsebenen), Hintergrund.
- **Slide Layouts:** alle Layouts mit Namen, Typ (Titel, Inhalt, Sektionstrenner, …) und
  sämtlichen Platzhaltern inkl. vererbter Position, Größe und Formatierung.
- **Bestehende Folien:** Inventar (Anzahl, Layoutzuordnung, Titel) für Inspektion.

Ergebnis ist ein vollständiges, abfragbares **Designmodell** des Templates.

### 3.2 Design-Treue (das Herzstück)

Neue Folien referenzieren die Original-Layouts des Masters. Dadurch erben sie automatisch
und verlustfrei: Hintergründe, Logos, Platzhalterpositionen, Schriften, Farben, Fußzeilen.
Eigene Elemente (Shapes, Tabellen, Diagramme) werden konsequent über **Theme-Farben**
(accent1–6, tx/bg) und **Theme-Schriften** gebaut — ändert sich der Master, ändern sich
die generierten Folien mit. Es gibt keine hartcodierten Fremdfarben.

### 3.3 Folien-Generierung (Builder)

- Neue Folie auf Basis jedes beliebigen Layouts (Auswahl per Name, Typ oder Index).
- Platzhalter befüllen: Titel, Untertitel, Body mit mehrstufigen Bullet-Hierarchien.
- Freie Elemente: Textboxen, Formen (Rechtecke, Pfeile, Chevrons, Linien, Ellipsen …),
  Bilder (PNG/JPEG, mit eigener Header-Analyse für Maße), Tabellen.
- Vollständige Text-Kontrolle: Schriftgröße, Fett/Kursiv, Farbe, Ausrichtung, Ebenen,
  Zeilen-/Absatzabstände, Aufzählungszeichen.
- Korrekte Registrierung im Paket: Content Types, Relationships, Slide-ID-Liste —
  die Datei ist nach jedem Speichern ein zu 100 % valides PPTX.

### 3.4 Consulting-Komponentenbibliothek

Vorgefertigte, theme-bewusste Bausteine in Beratungsqualität — alle aus nativen
PowerPoint-Shapes gebaut (dadurch nachträglich voll editierbar):

| Komponente | Einsatz |
|---|---|
| **Agenda-Folie** | nummerierte Agenda, aktiver Punkt hervorgehoben |
| **KPI-Kacheln** | Kennzahlen-Dashboard mit Wert, Label, Delta |
| **Harvey Balls** | qualitative Bewertungen (0/25/50/75/100 %) einzeln & als Matrix |
| **Wasserfall** | Brückenlogik für Effekte/Überleitungen, inkl. Summenbalken |
| **Balken-/Säulendiagramm** | shape-basiert, mit Werten und Achse |
| **Timeline / Roadmap** | Chevron-Phasen und Meilensteine |
| **Ampel-Status** | Rot/Gelb/Grün-Indikatoren |
| **Vergleichsmatrix** | Optionen × Kriterien, Zellen mit Text, Harvey oder Ampel |
| **Statustabelle** | formatierte Tabelle: Akzent-Header, Zebra-Zeilen, saubere Ränder |
| **Callout-Boxen** | Key Message / Warnung / Erfolg |

### 3.5 Drei Nutzungsebenen (Automatisierungsgrade)

1. **Python-API** — volle Kontrolle:
   ```python
   deck = Deck.open("firmen_master.pptx")
   s = deck.add_slide("Titel und Inhalt")
   s.title("Marktanalyse 2026")
   s.placeholder("body").bullets(["These 1", ("Beleg", 1), "These 2"])
   deck.save("ergebnis.pptx")
   ```
2. **JSON-Spezifikation** — deklarativ: Ein JSON beschreibt das ganze Deck
   (Folientypen, Inhalte, Daten); DeckForge rendert es gegen jedes Template.
3. **CLI** — vollautomatisch und pipeline-fähig:
   ```bash
   python3 -m deckforge inspect master.pptx
   python3 -m deckforge generate --template master.pptx --spec deck.json --out out.pptx
   python3 -m deckforge bootstrap --out template.pptx   # eigenes Default-Template
   ```
   Damit ist DeckForge der Renderer-Endpunkt jeder Automationskette (z. B. LLM erzeugt
   die JSON-Spec → DeckForge erzeugt das fertige Deck im Firmendesign).

## 4. Architekturprinzipien

1. **Zero Dependencies:** ausschließlich Python-Standardbibliothek (`zipfile`,
   `xml.etree`, `dataclasses`, `json`, `struct`, …). Kein `pip install`. Läuft auf jedem
   Rechner mit Python ≥ 3.9.
2. **Eigene OOXML-Engine:** OPC-Paket, Relationships, Content Types, DrawingML und
   PresentationML werden selbst gelesen und geschrieben — volle Kontrolle, volles
   Verständnis.
3. **Nicht-destruktiv:** Alle Original-Parts des Templates bleiben byte-identisch
   erhalten; es wird nur ergänzt, was für neue Folien nötig ist.
4. **Determinismus:** gleicher Input → byte-stabil gleicher Output (testbar, diffbar).
5. **Theme-first:** keine hartcodierten Farben/Schriften in generierten Inhalten.
6. **Editierbarkeit:** alles, was DeckForge erzeugt, ist in PowerPoint normal anklick-
   und änderbar (native Shapes, echte Platzhalter, echte Tabellen).

## 5. Qualitätskriterien (Definition of Done)

- Generierte Dateien öffnen in PowerPoint **ohne Reparaturdialog**.
- Round-Trip-Test: erzeugen → speichern → wieder einlesen → Modell identisch.
- Jedes Modul mit Unit-Tests (unittest, stdlib), plus End-to-End-Test, der ein
  vollständiges Demo-Deck mit allen Komponenten baut und strukturell validiert.
- Sonderzeichen-sicher (Umlaute, &, <, >, Emoji), leere Eingaben crashen nicht.
- Saubere, dokumentierte Public API; Fehler als sprechende Exceptions.

## 6. Nicht-Ziele (V1)

- Kein Rendern/Rasterisieren von Folien zu Bildern (das macht PowerPoint).
- Keine nativen Chart-Parts (`chart1.xml`) — Diagramme werden shape-basiert gebaut
  (robuster, editierbarer); native Charts sind Ausbaustufe.
- Kein Bearbeiten/Umformatieren *bestehender* Folien (nur Lesen + neue Folien); Editieren
  ist Ausbaustufe.
- Keine Animationen/Übergänge, keine eingebetteten Videos.

## 7. Ausbaustufen

- **V1 (dieses Repo):** Parser, Designmodell, Builder, Komponentenbibliothek, JSON-Spec,
  CLI, Bootstrap-Template, Testsuite.
- **V2:** native Charts, Bearbeiten bestehender Folien, Speaker Notes,
  Folien-Klonen zwischen Decks, weitere Komponenten (Gantt, Org-Chart, Heatmap).
- **V3:** Spec-Erweiterung für LLM-Workflows (Content-Pipelines), Stil-Linter
  („Folie verstößt gegen Master-Regeln“), Diff zweier Decks.

## 8. Erfolgskriterien

- Ein komplettes 10+-Folien-Consulting-Deck entsteht aus einem JSON in < 1 Sekunde.
- Ein neues Firmen-Template übernehmen = `Deck.open("neu.pptx")` — null Code-Änderung.
- Jede generierte Folie ist von einer handgebauten Folie im selben Master visuell
  nicht zu unterscheiden.
