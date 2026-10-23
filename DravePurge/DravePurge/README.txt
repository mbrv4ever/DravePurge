DravePurge - privacy-opruimer (Dravenlock)
=============================================
Versie 0.2.8  -  scannen, opruimen, witte lijst, back-up, terugzetten, logboek

Wat is het
----------
DravePurge ruimt privacygevoelige rommel op je pc op: browser-cache,
cookies, geschiedenis, formuliergegevens en tijdelijke Windows-bestanden.
Alles blijft lokaal en offline. Het is gratis (donationware) - een vrijwillige
donatie wordt zeer gewaardeerd.

Starten
-------
  - Dubbelklik op run.bat. De eerste keer wordt automatisch een kleine
    omgeving (.venv) gemaakt en PyQt6 geinstalleerd. Daarna start de app.
  - Werkt iets niet? Start start-debug.bat; die toont eventuele fouten.
  - herstel.bat verwijdert de omgeving en bouwt hem opnieuw op.

Zo werkt het
------------
  - 1) Scannen. DravePurge zoekt zelf welke browsers er zijn (Chrome, Edge,
       Brave, Firefox, Opera, Vivaldi, ...) en welke systeem-rommel er is, met
       per categorie de grootte en het aantal bestanden.
  - 2) Aanvinken wat weg mag. Cookies en formuliergegevens staan standaard UIT
       voor de veiligheid; vink ze zelf aan als je ze toch wilt wissen.
  - 3) Opruimen. Je krijgt eerst een overzicht en kunt (aanbevolen) eerst een
       back-up laten maken. Pas na bevestiging wordt er definitief opgeruimd.

  - Witte lijst...: geef sites op waarvan de cookies behouden blijven, zodat je
    daar ingelogd blijft. Zonder witte lijst worden ALLE cookies gewist.
  - Back-up maken / Terugzetten...: bewaar je waardevolle browsergegevens en zet
    ze terug als je per ongeluk iets wist.
  - Belangrijk: sluit je browsers voor het opruimen/terugzetten - anders zijn
    bestanden vergrendeld en worden ze overgeslagen.

Is dit veilig?
--------------
Ja. DravePurge werkt volledig lokaal en offline: het leest en verwijdert alleen
bestanden op je eigen pc en stuurt niets naar internet.
Je antivirus of Windows SmartScreen kan toch waarschuwen, om twee onschuldige
redenen: het is een nieuw, niet-ondertekend programma (onbekende uitgever), en
het verwijdert bestanden en leest browsergegevens - gedrag waar virusscanners
op letten. Het is een vals alarm.
  - SmartScreen (Windows heeft uw pc beschermd): klik Meer informatie, dan
    Toch uitvoeren.
  - Blijft de antivirus moeilijk doen: voeg de DravePurge-map als uitzondering
    toe.
  - Voor extra gerustheid: maak eerst een back-up (dat kan de app zelf).

Losse .exe maken (optioneel)
----------------------------
  - Voer run.bat een keer uit, daarna bouw-exe.bat. De exe komt in dist\.

Contact / donatie
-----------------
  service@dravenlock.nl   -   paypal.me/roger076
