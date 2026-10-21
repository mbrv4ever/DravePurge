# -*- coding: utf-8 -*-
"""
DravePurge - privacy-opruimer (Dravenlock)
v0.1: ALLEEN SCANNEN. Detecteert browsers (Chromium-familie + Firefox) en
systeem-rommel en toont per categorie hoeveel er te vinden is. Er wordt in deze
versie NIETS verwijderd - dat komt in v0.2 (met bevestiging en cookie-witte-lijst).
"""
import os
import sys
import re
import json
import zipfile
import sqlite3
import subprocess
import datetime
import traceback

APP_NAAM = "DravePurge"
APP_VERSIE = "0.2.9"
DONATIE_URL = "https://paypal.me/roger076"
CONTACT = "service@dravenlock.nl"

BASIS = os.path.dirname(os.path.abspath(__file__))
FOUT_BESTAND = os.path.join(BASIS, "app-fout.txt")
CONFIG_BESTAND = os.path.join(BASIS, "config.json")

STANDAARD_CONFIG = {
    "taal": "auto",
    "cookie_witte_lijst": [],
    "backup_map": "",
    "toon_welkom": True,
}


def laad_config():
    cfg = dict(STANDAARD_CONFIG)
    try:
        with open(CONFIG_BESTAND, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            cfg.update(data)
    except Exception:
        pass
    return cfg


def bewaar_config(cfg):
    """Schrijf veilig (temp + os.replace)."""
    try:
        tmp = CONFIG_BESTAND + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.replace(tmp, CONFIG_BESTAND)
    except Exception:
        pass


def normaliseer_domein(s):
    """Maak er een kaal domein van: zonder protocol, pad of 'www.'."""
    s = (s or "").strip().lower()
    s = re.sub(r"^[a-z]+://", "", s)   # protocol weg
    s = s.split("/")[0].split("?")[0]  # pad/query weg
    if s.startswith("www."):
        s = s[4:]
    return s


def _schrijf_startfout(tekst):
    try:
        with open(FOUT_BESTAND, "w", encoding="utf-8") as f:
            f.write(tekst)
    except Exception:
        pass


def _excepthook(t, w, tb):
    _schrijf_startfout("".join(traceback.format_exception(t, w, tb)))
    sys.__excepthook__(t, w, tb)


sys.excepthook = _excepthook

try:
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl, QLocale, QSize, QTimer
    from PyQt6.QtGui import (
        QAction, QIcon, QDesktopServices, QFont, QColor, QPixmap, QPalette,
    )
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
        QPushButton, QTreeWidget, QTreeWidgetItem, QHeaderView, QProgressBar,
        QStatusBar, QMessageBox, QDialog, QTextBrowser, QComboBox, QFormLayout,
        QDialogButtonBox, QAbstractItemView, QListWidget, QLineEdit, QCheckBox,
    )
except Exception as e:  # pragma: no cover
    _schrijf_startfout("PyQt6 kon niet geladen worden:\n%r\n" % e)
    raise


# ---------------------------------------------------------------------------
# Huisstijl (Dravenlock)
# ---------------------------------------------------------------------------
BG = "#0e0e11"
PANEL = "#16161b"
PANEL2 = "#1c1c22"
TEXT = "#d4d4d4"
MUTED = "#8a8a94"
ACCENT = "#6fa3d6"
ACCENT_DIM = "#4d7aa8"
LINE = "#23232b"
WAARSCHUW = "#d68a6f"


# ---------------------------------------------------------------------------
# Hulpfuncties
# ---------------------------------------------------------------------------
def mensvriendelijke_grootte(n):
    n = float(n)
    for eenheid in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or eenheid == "TB":
            if eenheid == "B":
                return "%d B" % int(n)
            return "%.1f %s" % (n, eenheid)
        n /= 1024.0


def pad_uit(sjabloon):
    """Vervang %VAR%-omgevingsvariabelen en geef een absoluut pad terug.
    Werkt op elk platform (Windows %VAR% wordt handmatig uit de omgeving
    gehaald), zodat detectie ook testbaar is buiten Windows."""
    def vervang(m):
        return os.environ.get(m.group(1), m.group(0))
    uit = re.sub(r"%([^%]+)%", vervang, sjabloon)
    uit = os.path.expandvars(uit)
    return uit.replace("\\", os.sep)


def map_grootte(pad):
    """Som van bestandsgroottes in een map (recursief). Geeft (bytes, aantal)."""
    totaal = 0
    aantal = 0
    for wortel, mappen, bestanden in os.walk(pad):
        for b in bestanden:
            try:
                totaal += os.path.getsize(os.path.join(wortel, b))
                aantal += 1
            except (OSError, PermissionError):
                pass
    return totaal, aantal


def pad_grootte(pad):
    """Grootte van een bestand of map. Geeft (bytes, aantal_bestanden)."""
    try:
        if os.path.isdir(pad):
            return map_grootte(pad)
        if os.path.isfile(pad):
            return os.path.getsize(pad), 1
    except (OSError, PermissionError):
        pass
    return 0, 0


# ---------------------------------------------------------------------------
# Browser-register (data-gestuurd, dus eenvoudig uit te breiden)
# ---------------------------------------------------------------------------
# Chromium-familie: "User Data" met profielmappen (Default, Profile 1, ...).
CHROMIUM = [
    # (naam, profiel-basis, cache-basis of None als cache onder het profiel staat)
    ("Google Chrome",  r"%LOCALAPPDATA%\Google\Chrome\User Data", None),
    ("Microsoft Edge", r"%LOCALAPPDATA%\Microsoft\Edge\User Data", None),
    ("Brave",          r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data", None),
    ("Vivaldi",        r"%LOCALAPPDATA%\Vivaldi\User Data", None),
    ("Chromium",       r"%LOCALAPPDATA%\Chromium\User Data", None),
    # Opera: profieldata onder Roaming, maar de CACHE onder Local.
    ("Opera",          r"%APPDATA%\Opera Software\Opera Stable",
                       r"%LOCALAPPDATA%\Opera Software\Opera Stable"),
    ("Opera GX",       r"%APPDATA%\Opera Software\Opera GX Stable",
                       r"%LOCALAPPDATA%\Opera Software\Opera GX Stable"),
]
# Firefox: profielmap onder Roaming; cache staat apart onder Local.
FIREFOX_PROFIELEN = r"%APPDATA%\Mozilla\Firefox\Profiles"
FIREFOX_CACHE = r"%LOCALAPPDATA%\Mozilla\Firefox\Profiles"

# Categorie-onderdelen per Chromium-profiel (paden relatief aan het profiel).
CHROMIUM_CATS = {
    "cache": ["Cache", "Code Cache", "GPUCache", "GrShaderCache", "ShaderCache",
              os.path.join("Service Worker", "CacheStorage"),
              os.path.join("Service Worker", "ScriptCache")],
    "cookies": [os.path.join("Network", "Cookies"), "Cookies"],
    "geschiedenis": ["History", "History-journal", "Visited Links",
                     "Top Sites", "Network Action Predictor"],
    "formulieren": ["Web Data", "Web Data-journal"],
    "sessies": ["Sessions", "Current Session", "Last Session",
                "Current Tabs", "Last Tabs"],
}
FIREFOX_CATS = {
    "cookies": ["cookies.sqlite", "cookies.sqlite-wal"],
    "geschiedenis": ["places.sqlite", "places.sqlite-wal"],
    "formulieren": ["formhistory.sqlite"],
    "sessies": ["sessionstore.jsonlz4", "sessionstore-backups"],
}

# Categorieen die standaard NIET worden aangevinkt (gevoelig maar nuttig om te
# behouden). Worden wel getoond, maar niet opgeruimd tenzij de gebruiker ze
# zelf aanvinkt. Cookies staan standaard uit voor de veiligheid: pas als je een
# witte lijst hebt ingesteld weet je zeker dat je ingelogd blijft.
STANDAARD_UIT = {"formulieren", "cookies"}
SUFFIX_SLEUTEL = {"formulieren": "behouden_suffix", "cookies": "cookies_suffix"}


def chromium_profielen(basis):
    """Vind profielmappen binnen een Chromium 'User Data'-map."""
    profielen = []
    if not os.path.isdir(basis):
        return profielen
    # Opera Stable is zelf het profiel (geen User Data/Profile-structuur)
    if os.path.exists(os.path.join(basis, "Preferences")) or \
       os.path.exists(os.path.join(basis, "Cookies")) or \
       os.path.exists(os.path.join(basis, "Network", "Cookies")):
        profielen.append(("", basis))
    try:
        for naam in sorted(os.listdir(basis)):
            p = os.path.join(basis, naam)
            if not os.path.isdir(p):
                continue
            if naam == "Default" or naam.startswith("Profile ") or \
               os.path.exists(os.path.join(p, "Preferences")):
                profielen.append((naam, p))
    except (OSError, PermissionError):
        pass
    return profielen


def detecteer_browsers():
    """Geef een lijst gevonden browserprofielen met hun categorie-onderdelen."""
    gevonden = []
    # Chromium-familie
    for naam, sjabloon, cache_sjabloon in CHROMIUM:
        basis = pad_uit(sjabloon)
        cache_basis = pad_uit(cache_sjabloon) if cache_sjabloon else basis
        for profielnaam, profielpad in chromium_profielen(basis):
            # cache-profielmap: dezelfde profielnaam, maar onder de cache-basis
            cache_profiel = (os.path.join(cache_basis, profielnaam)
                             if profielnaam else cache_basis)
            onderdelen = []
            for cat, relpaden in CHROMIUM_CATS.items():
                if cat == "cache":
                    # cache kan onder het profiel staan (Chrome e.d.) of in een
                    # aparte cache-basis (Opera); zoek op beide plekken.
                    wortels = [profielpad]
                    if cache_profiel != profielpad:
                        wortels.append(cache_profiel)
                else:
                    wortels = [profielpad]
                paden = [os.path.join(w, r) for w in wortels for r in relpaden]
                onderdelen.append((cat, paden))
            gevonden.append({
                "naam": naam,
                "profiel": profielnaam,
                "soort": "chromium",
                "onderdelen": onderdelen,
            })
    # Firefox
    basis = pad_uit(FIREFOX_PROFIELEN)
    cache_basis = pad_uit(FIREFOX_CACHE)
    if os.path.isdir(basis):
        try:
            for profielnaam in sorted(os.listdir(basis)):
                profielpad = os.path.join(basis, profielnaam)
                if not os.path.isdir(profielpad):
                    continue
                onderdelen = []
                # cache apart (onder Local)
                cache_pad = os.path.join(cache_basis, profielnaam, "cache2")
                onderdelen.append(("cache", [cache_pad]))
                for cat, relpaden in FIREFOX_CATS.items():
                    paden = [os.path.join(profielpad, r) for r in relpaden]
                    onderdelen.append((cat, paden))
                gevonden.append({
                    "naam": "Mozilla Firefox",
                    "profiel": profielnaam,
                    "soort": "firefox",
                    "onderdelen": onderdelen,
                })
        except (OSError, PermissionError):
            pass
    return gevonden


def systeem_onderdelen():
    """Windows/systeem-rommel (paden kunnen leeg/afwezig zijn op niet-Windows)."""
    onderdelen = []
    temp_paden = []
    for s in ("%TEMP%", r"%SystemRoot%\Temp"):
        p = pad_uit(s)
        if p and "%" not in p:
            temp_paden.append(p)
    onderdelen.append(("temp", temp_paden))
    onderdelen.append(("recent", [pad_uit(r"%APPDATA%\Microsoft\Windows\Recent")]))
    onderdelen.append(("miniaturen",
                       [pad_uit(r"%LOCALAPPDATA%\Microsoft\Windows\Explorer")]))
    return onderdelen


# ---------------------------------------------------------------------------
# Back-up & terugzetten (veiligheidsnet)
# ---------------------------------------------------------------------------
# Categorieen die de moeite waard zijn om te bewaren (NIET de cache/temp).
WAARDEVOL_CATS = {"cookies", "geschiedenis", "formulieren", "sessies"}


def backup_map_pad(cfg):
    p = (cfg.get("backup_map") or "").strip()
    return p if p else os.path.join(BASIS, "DravePurge-backups")


def verzamel_waardevolle_bestanden():
    """Alle losse bestanden uit de waardevolle categorieen van alle browsers."""
    bestanden = []
    for b in detecteer_browsers():
        for cat, paden in b["onderdelen"]:
            if cat not in WAARDEVOL_CATS:
                continue
            for p in paden:
                if os.path.isfile(p):
                    bestanden.append(p)
                elif os.path.isdir(p):
                    for wortel, _mappen, best in os.walk(p):
                        for f in best:
                            bestanden.append(os.path.join(wortel, f))
    return bestanden


def maak_backup(doelmap, voortgang=None, gestopt=None):
    """Kopieer waardevolle gegevens naar een tijdgestempelde zip met manifest.
    Geeft (zip_pad, aantal_bewaard, aantal_overgeslagen)."""
    os.makedirs(doelmap, exist_ok=True)
    stempel = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    zip_pad = os.path.join(doelmap, "backup_%s.zip" % stempel)
    bestanden = verzamel_waardevolle_bestanden()
    manifest = {"app": APP_NAAM, "versie": APP_VERSIE, "datum": stempel,
                "bestanden": []}
    overgeslagen = 0
    with zipfile.ZipFile(zip_pad, "w", zipfile.ZIP_DEFLATED) as z:
        for i, p in enumerate(bestanden, 1):
            if gestopt and gestopt():
                break
            arc = "d/%06d" % i
            try:
                z.write(p, arc)
                manifest["bestanden"].append(
                    {"id": arc, "pad": os.path.abspath(p),
                     "grootte": os.path.getsize(p)})
                if voortgang:
                    voortgang(p)
            except (OSError, PermissionError):
                overgeslagen += 1   # vergrendeld (browser open) -> overslaan
        z.writestr("manifest.json",
                   json.dumps(manifest, ensure_ascii=False, indent=1))
    return zip_pad, len(manifest["bestanden"]), overgeslagen


def lees_backups(map_pad):
    """Lijst beschikbare back-ups (nieuste eerst) met wat metadata."""
    uit = []
    if not os.path.isdir(map_pad):
        return uit
    for naam in os.listdir(map_pad):
        if not (naam.startswith("backup_") and naam.endswith(".zip")):
            continue
        vol = os.path.join(map_pad, naam)
        info = {"pad": vol, "naam": naam, "aantal": 0, "grootte": 0,
                "datum": ""}
        try:
            info["grootte"] = os.path.getsize(vol)
            with zipfile.ZipFile(vol, "r") as z:
                m = json.loads(z.read("manifest.json").decode("utf-8"))
                info["aantal"] = len(m.get("bestanden", []))
                info["datum"] = m.get("datum", "")
        except Exception:
            continue
        uit.append(info)
    uit.sort(key=lambda x: x["naam"], reverse=True)
    return uit


def zet_backup_terug(zip_pad, voortgang=None, gestopt=None):
    """Zet bestanden uit een back-up terug op hun oorspronkelijke plek.
    Geeft (aantal_teruggezet, aantal_mislukt)."""
    teruggezet = 0
    mislukt = 0
    with zipfile.ZipFile(zip_pad, "r") as z:
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        for item in manifest.get("bestanden", []):
            if gestopt and gestopt():
                break
            doel = item.get("pad")
            arc = item.get("id")
            if not doel or not arc:
                continue
            try:
                map_ = os.path.dirname(doel)
                if map_:
                    os.makedirs(map_, exist_ok=True)
                with z.open(arc) as bron:
                    data = bron.read()
                tmp = doel + ".dpnew"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, doel)
                teruggezet += 1
                if voortgang:
                    voortgang(doel)
            except (OSError, PermissionError):
                mislukt += 1   # vergrendeld (browser open) -> overslaan
    return teruggezet, mislukt


# ---------------------------------------------------------------------------
# Opruimen (v0.2) - DESTRUCTIEF. Werkt alleen op de gescande, aangevinkte paden.
# ---------------------------------------------------------------------------
def _foutreden(e):
    """Korte, leesbare reden waarom iets niet lukte."""
    reden = type(e).__name__
    win = getattr(e, "winerror", None)
    if win:
        reden += " (WinError %s)" % win
    elif getattr(e, "errno", None):
        reden += " (errno %s)" % e.errno
    boodschap = getattr(e, "strerror", None) or str(e)
    if boodschap and boodschap not in reden:
        reden += ": " + boodschap
    return reden


def _verwijder_pad(p, alleen_inhoud=False):
    """Verwijder een bestand, of de inhoud van een map (bottom-up).
    Geeft (bytes_vrij, verwijderd, overgeslagen, fouten) waarbij fouten een
    lijst is van (pad, reden)."""
    bytes_vrij = verwijderd = overgeslagen = 0
    fouten = []
    if not (os.path.isfile(p) or os.path.islink(p) or os.path.isdir(p)):
        # niets aanwezig op dit pad -> niets te doen (geen fout)
        return bytes_vrij, verwijderd, overgeslagen, fouten
    try:
        if os.path.isfile(p) or os.path.islink(p):
            try:
                sz = os.path.getsize(p)
                os.remove(p)
                bytes_vrij += sz
                verwijderd += 1
            except (OSError, PermissionError) as e:
                overgeslagen += 1
                fouten.append((p, _foutreden(e)))
        elif os.path.isdir(p):
            for wortel, mappen, best in os.walk(p, topdown=False):
                for f in best:
                    fp = os.path.join(wortel, f)
                    try:
                        sz = os.path.getsize(fp)
                        os.remove(fp)
                        bytes_vrij += sz
                        verwijderd += 1
                    except (OSError, PermissionError) as e:
                        overgeslagen += 1
                        fouten.append((fp, _foutreden(e)))
                for d in mappen:
                    try:
                        os.rmdir(os.path.join(wortel, d))   # alleen als leeg
                    except OSError:
                        pass
            if not alleen_inhoud:
                try:
                    os.rmdir(p)
                except OSError:
                    pass
    except (OSError, PermissionError) as e:
        overgeslagen += 1
        fouten.append((p, _foutreden(e)))
    return bytes_vrij, verwijderd, overgeslagen, fouten


def _cookies_selectief(pad, soort, witte_lijst):
    """Verwijder cookies behalve die van de witte-lijst-domeinen (en subdomeinen).
    Geeft (bytes_vrij, verwijderd, overgeslagen, fouten)."""
    tabel, kolom = (("cookies", "host_key") if soort == "chromium"
                    else ("moz_cookies", "host"))
    try:
        sz_voor = os.path.getsize(pad)
        con = sqlite3.connect(pad, timeout=2.0)
        cur = con.cursor()
        cur.execute("SELECT rowid, %s FROM %s" % (kolom, tabel))
        weg = []
        for rowid, host in cur.fetchall():
            h = (host or "").lstrip(".").lower()
            behouden = any(h == d or h.endswith("." + d) for d in witte_lijst)
            if not behouden:
                weg.append(rowid)
        for rowid in weg:
            cur.execute("DELETE FROM %s WHERE rowid=?" % tabel, (rowid,))
        con.commit()
        # Zijn er nog cookies over (bv. van de witte lijst)?
        cur.execute("SELECT COUNT(*) FROM %s" % tabel)
        rest = cur.fetchone()[0]
        if rest == 0:
            # niets meer over -> verwijder het lege bestand zelf, zodat het ook
            # uit de scan verdwijnt (de browser maakt het opnieuw aan).
            con.close()
            vrij = 0
            for extra in (pad, pad + "-wal", pad + "-shm", pad + "-journal"):
                try:
                    vrij += os.path.getsize(extra)
                    os.remove(extra)
                except OSError:
                    pass
            return vrij, len(weg), 0, []
        try:
            cur.execute("VACUUM")
            con.commit()
        except Exception:
            pass
        con.close()
        sz_na = os.path.getsize(pad)
        return max(0, sz_voor - sz_na), len(weg), 0, []
    except Exception as e:
        return 0, 0, 1, [(pad, _foutreden(e))]


def maak_schoon(onderdelen, witte_lijst, voortgang=None, gestopt=None):
    """onderdelen: lijst {'cat','soort','paden','label'}. Geeft (bytes_vrij,
    verwijderd, overgeslagen, logregels)."""
    bytes_vrij = verwijderd = overgeslagen = 0
    logregels = []
    for o in onderdelen:
        if gestopt and gestopt():
            break
        cat, soort, paden = o["cat"], o.get("soort", ""), o["paden"]
        label = o.get("label", soort or "systeem")
        if voortgang:
            voortgang(cat)
        ob = ov = osk = 0
        ofouten = []
        for p in paden:
            if (cat == "cookies" and witte_lijst
                    and soort in ("chromium", "firefox") and os.path.isfile(p)):
                b, v, s, f = _cookies_selectief(p, soort, witte_lijst)
            else:
                b, v, s, f = _verwijder_pad(p, alleen_inhoud=(cat == "temp"))
            ob += b
            ov += v
            osk += s
            ofouten += f
        bytes_vrij += ob
        verwijderd += ov
        overgeslagen += osk
        logregels.append("[%s / %s] %d verwijderd, %d overgeslagen, %s vrij" %
                         (label, cat, ov, osk, mensvriendelijke_grootte(ob)))
        for pad, reden in ofouten[:40]:
            logregels.append("    OVERGESLAGEN: %s  ->  %s" % (pad, reden))
        if len(ofouten) > 40:
            logregels.append("    ... en nog %d overgeslagen" % (len(ofouten) - 40))
    return bytes_vrij, verwijderd, overgeslagen, logregels


def draaiende_browsers():
    """Best-effort: welke bekende browsers draaien er (Windows)."""
    if os.name != "nt":
        return []
    try:
        vlaggen = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            vlaggen = subprocess.CREATE_NO_WINDOW   # geen consolevenster
        uit = subprocess.run(["tasklist"], capture_output=True, text=True,
                             timeout=5, creationflags=vlaggen).stdout.lower()
    except Exception:
        return []
    procs = {"chrome.exe": "Chrome", "msedge.exe": "Edge",
             "brave.exe": "Brave", "firefox.exe": "Firefox",
             "opera.exe": "Opera", "vivaldi.exe": "Vivaldi"}
    return sorted({naam for exe, naam in procs.items() if exe in uit})


# ---------------------------------------------------------------------------
# i18n
# ---------------------------------------------------------------------------
TEKST = {
    "nl": {
        "titel": "DravePurge",
        "ondertitel": "Privacy-opruimer - lokaal en offline",
        "scannen": "Scannen",
        "bezig": "Bezig met scannen...",
        "opruimen": "Opruimen",
        "opruim_titel": "Opruimen",
        "opruim_niets": ("Niets aangevinkt om op te ruimen. Doe eerst een scan "
                         "en vink aan wat weg mag."),
        "opruim_overzicht": "Dit wordt definitief opgeruimd:",
        "opruim_totaal": "Totaal: {grootte} in {n} categorieen.",
        "opruim_backup_eerst": "Eerst een back-up maken (aanbevolen)",
        "opruim_cookies_witlijst": "Cookies van deze sites blijven behouden: {sites}",
        "opruim_cookies_alles": ("LET OP: er is geen witte lijst, dus ALLE cookies "
                                 "worden gewist en je raakt overal uitgelogd."),
        "opruim_sluit_browser": ("Sluit eerst je browsers; vergrendelde bestanden "
                                 "worden anders overgeslagen."),
        "opruim_draait": "Deze browsers lijken nog te draaien: {namen}.",
        "opruim_knop": "Nu opruimen",
        "opruim_bezig": "Opruimen...",
        "opruim_klaar": "Klaar: {grootte} vrijgemaakt, {n} items verwijderd.",
        "opruim_klaar_over": ("Klaar: {grootte} vrijgemaakt, {n} verwijderd, "
                              "{over} overgeslagen omdat ze in gebruik waren "
                              "(normaal voor tijdelijke bestanden)."),
        "opruim_niets_kort": "Niets opgeruimd - zie logboek voor de reden.",
        "opruim_niets_vrij": ("Er is niets opgeruimd: alle {over} items zijn "
                              "overgeslagen.\n\nIk open hieronder het logboek; daarin "
                              "staat per bestand de exacte reden (bijv. 'in gebruik', "
                              "'toegang geweigerd' of 'niet gevonden'). Stuur me die "
                              "regels door, dan zie ik precies wat er misgaat."),
        "opruim_log": "Logboek: {pad}",
        "klaar_scan": "Scan klaar: {grootte} aan op te ruimen items gevonden.",
        "niets": "Niets gevonden om op te ruimen.",
        "geen_browsers": "Geen browsers of systeem-rommel gevonden.",
        "kolom_item": "Categorie",
        "kolom_grootte": "Grootte",
        "kolom_aantal": "Bestanden",
        "systeem": "Windows / Systeem",
        "cache": "Cache (tijdelijke bestanden)",
        "cookies": "Cookies",
        "geschiedenis": "Geschiedenis",
        "formulieren": "Formuliergegevens (autofill)",
        "behouden_suffix": "  -  standaard behouden",
        "cookies_suffix": "  -  standaard uit (zie witte lijst)",
        "witte_lijst": "Cookie-witte-lijst",
        "witte_lijst_knop": "Witte lijst...",
        "witte_lijst_uitleg": ("Cookies van deze sites blijven behouden bij het "
                               "opruimen, zodat je ingelogd blijft."),
        "domein_invoer": "bijv. google.com",
        "toevoegen": "Toevoegen",
        "verwijderen": "Verwijderen",
        "witte_lijst_leeg": "Nog geen sites op de witte lijst.",
        "opslaan": "Opslaan",
        "annuleren": "Annuleren",
        "backup_maken": "Back-up maken",
        "terugzetten": "Terugzetten...",
        "backup_bezig": "Back-up maken...",
        "backup_klaar": "Back-up gemaakt: {n} bestanden bewaard.",
        "backup_klaar_over": "Back-up gemaakt: {n} bestanden bewaard, {over} overgeslagen (browser open?).",
        "backup_mislukt": "Back-up mislukt: {fout}",
        "backup_sluit_tip": "Tip: sluit je browsers voor een volledige back-up.",
        "terugzet_titel": "Back-up terugzetten",
        "terugzet_uitleg": ("Kies een back-up om terug te zetten. Sluit eerst je "
                            "browsers, anders zijn de bestanden vergrendeld."),
        "terugzet_bevestig": ("De bestanden uit deze back-up worden teruggezet en "
                              "bestaande bestanden worden overschreven. Doorgaan?"),
        "terugzet_bezig": "Terugzetten...",
        "terugzet_klaar": "{n} bestanden teruggezet.",
        "terugzet_klaar_mislukt": "{n} teruggezet, {m} mislukt (browser open?).",
        "geen_backups": "Nog geen back-ups gevonden.",
        "backup_item": "{datum}  -  {n} bestanden  -  {grootte}",
        "map_openen": "Map openen",
        "welkom_titel": "Welkom bij DravePurge",
        "welkom_intro": ("DravePurge ruimt privacygevoelige rommel van je browsers "
                         "en Windows op. Alles gebeurt lokaal; er gaat niets naar "
                         "internet."),
        "welkom_waarschuwing": ("Let op: opruimen verwijdert bestanden DEFINITIEF. "
                                "Dit kan niet ongedaan worden gemaakt, behalve via "
                                "een back-up."),
        "welkom_stappen_kop": "Doe dit de eerste keer, in deze volgorde:",
        "welkom_stap1": "1. Lees de Snelgids zodat je weet wat er gebeurt.",
        "welkom_stap2": ("2. Stel je Witte lijst in (sites waar je ingelogd wilt "
                         "blijven)."),
        "welkom_stap3": "3. Maak een Back-up als vangnet.",
        "welkom_daarna": ("Daarna kun je veilig scannen en opruimen. Cookies en "
                          "formuliergegevens staan standaard uit."),
        "welkom_snelgids": "Snelgids lezen",
        "welkom_witlijst": "Witte lijst instellen",
        "welkom_backup": "Back-up maken",
        "welkom_niet_meer": "Dit venster niet meer tonen bij opstarten",
        "welkom_start": "Aan de slag",
        "welkom_veilig": ("Veilig? DravePurge werkt lokaal en offline en stuurt "
                          "niets naar internet. Je antivirus kan een nieuwe "
                          "opruim-app toch even waarschuwen - dat is een vals "
                          "alarm. Meer hierover in de Snelgids."),
        "welkom_menu": "Welkom / waarschuwing",
        "sessies": "Sessies / open tabbladen",
        "temp": "Tijdelijke bestanden (temp)",
        "recent": "Recente-bestandenlijst",
        "miniaturen": "Miniatuur-cache",
        "v01_info": ("Tip: maak eerst een back-up en stel je witte lijst in. "
                     "Cookies en formuliergegevens staan standaard uit."),
        "menu_help": "Help",
        "snelgids": "Snelgids",
        "over": "Over",
        "instellingen": "Instellingen",
        "taal": "Taal",
        "taal_auto": "Automatisch (computertaal)",
        "donatie": "Donatie",
        "sluiten": "Sluiten",
        "opruimen_nog_niet": ("Opruimen zit nog niet in deze versie. v0.1 scant "
                              "alleen, zodat je eerst kunt controleren of alles "
                              "goed gevonden wordt. Het echte opruimen komt in v0.2."),
    },
    "en": {
        "titel": "DravePurge",
        "ondertitel": "Privacy cleaner - local and offline",
        "scannen": "Scan",
        "bezig": "Scanning...",
        "opruimen": "Clean up",
        "opruim_titel": "Clean up",
        "opruim_niets": ("Nothing ticked to clean. Run a scan first and tick "
                         "what may go."),
        "opruim_overzicht": "This will be permanently cleaned:",
        "opruim_totaal": "Total: {grootte} in {n} categories.",
        "opruim_backup_eerst": "Make a backup first (recommended)",
        "opruim_cookies_witlijst": "Cookies of these sites are kept: {sites}",
        "opruim_cookies_alles": ("WARNING: there is no whitelist, so ALL cookies "
                                 "are cleared and you will be logged out everywhere."),
        "opruim_sluit_browser": ("Close your browsers first; locked files are "
                                 "skipped otherwise."),
        "opruim_draait": "These browsers still seem to be running: {namen}.",
        "opruim_knop": "Clean up now",
        "opruim_bezig": "Cleaning...",
        "opruim_klaar": "Done: {grootte} freed, {n} items removed.",
        "opruim_klaar_over": ("Done: {grootte} freed, {n} removed, {over} skipped "
                              "because they were in use (normal for temp files)."),
        "opruim_niets_kort": "Nothing cleaned - see log for the reason.",
        "opruim_niets_vrij": ("Nothing was cleaned: all {over} items were "
                              "skipped.\n\nI'll open the log below; it shows the "
                              "exact reason per file (e.g. 'in use', 'access denied' "
                              "or 'not found'). Send me those lines and I'll see "
                              "exactly what goes wrong."),
        "opruim_log": "Log: {pad}",
        "klaar_scan": "Scan done: {grootte} of removable items found.",
        "niets": "Nothing found to clean.",
        "geen_browsers": "No browsers or system junk found.",
        "kolom_item": "Category",
        "kolom_grootte": "Size",
        "kolom_aantal": "Files",
        "systeem": "Windows / System",
        "cache": "Cache (temporary files)",
        "cookies": "Cookies",
        "geschiedenis": "History",
        "formulieren": "Form data (autofill)",
        "behouden_suffix": "  -  kept by default",
        "cookies_suffix": "  -  off by default (see whitelist)",
        "witte_lijst": "Cookie whitelist",
        "witte_lijst_knop": "Whitelist...",
        "witte_lijst_uitleg": ("Cookies of these sites are kept during cleaning, "
                               "so you stay logged in."),
        "domein_invoer": "e.g. google.com",
        "toevoegen": "Add",
        "verwijderen": "Remove",
        "witte_lijst_leeg": "No sites on the whitelist yet.",
        "opslaan": "Save",
        "annuleren": "Cancel",
        "backup_maken": "Make backup",
        "terugzetten": "Restore...",
        "backup_bezig": "Making backup...",
        "backup_klaar": "Backup made: {n} files saved.",
        "backup_klaar_over": "Backup made: {n} files saved, {over} skipped (browser open?).",
        "backup_mislukt": "Backup failed: {fout}",
        "backup_sluit_tip": "Tip: close your browsers for a complete backup.",
        "terugzet_titel": "Restore backup",
        "terugzet_uitleg": ("Choose a backup to restore. Close your browsers "
                            "first, otherwise the files are locked."),
        "terugzet_bevestig": ("The files from this backup will be restored and "
                              "existing files will be overwritten. Continue?"),
        "terugzet_bezig": "Restoring...",
        "terugzet_klaar": "{n} files restored.",
        "terugzet_klaar_mislukt": "{n} restored, {m} failed (browser open?).",
        "geen_backups": "No backups found yet.",
        "backup_item": "{datum}  -  {n} files  -  {grootte}",
        "map_openen": "Open folder",
        "welkom_titel": "Welcome to DravePurge",
        "welkom_intro": ("DravePurge cleans up privacy-sensitive junk from your "
                         "browsers and Windows. Everything happens locally; "
                         "nothing goes online."),
        "welkom_waarschuwing": ("Note: cleaning deletes files PERMANENTLY. This "
                                "cannot be undone, except via a backup."),
        "welkom_stappen_kop": "Do this the first time, in this order:",
        "welkom_stap1": "1. Read the Quick guide so you know what happens.",
        "welkom_stap2": ("2. Set up your Whitelist (sites you want to stay logged "
                         "in to)."),
        "welkom_stap3": "3. Make a Backup as a safety net.",
        "welkom_daarna": ("After that you can safely scan and clean. Cookies and "
                          "form data are off by default."),
        "welkom_snelgids": "Read quick guide",
        "welkom_witlijst": "Set up whitelist",
        "welkom_backup": "Make backup",
        "welkom_niet_meer": "Do not show this window at startup",
        "welkom_start": "Get started",
        "welkom_veilig": ("Safe? DravePurge works locally and offline and sends "
                          "nothing to the internet. Your antivirus may still warn "
                          "about a new cleaning app - that is a false alarm. More "
                          "in the Quick guide."),
        "welkom_menu": "Welcome / warning",
        "sessies": "Sessions / open tabs",
        "temp": "Temporary files (temp)",
        "recent": "Recent files list",
        "miniaturen": "Thumbnail cache",
        "v01_info": ("Tip: make a backup first and set up your whitelist. "
                     "Cookies and form data are off by default."),
        "menu_help": "Help",
        "snelgids": "Quick guide",
        "over": "About",
        "instellingen": "Settings",
        "taal": "Language",
        "taal_auto": "Automatic (system language)",
        "donatie": "Donate",
        "sluiten": "Close",
        "opruimen_nog_niet": ("Cleaning is not in this version yet. v0.1 only "
                             "scans so you can first check that everything is "
                             "found correctly. The actual cleaning comes in v0.2."),
    },
}


def detecteer_taal():
    try:
        naam = QLocale.system().name()  # bv. nl_NL
        if naam.lower().startswith("nl"):
            return "nl"
    except Exception:
        pass
    return "en"


# ---------------------------------------------------------------------------
# Scan-thread (houdt de UI responsief)
# ---------------------------------------------------------------------------
class ScanThread(QThread):
    voortgang = pyqtSignal(str)
    klaar = pyqtSignal(list)   # lijst groepen met berekende groottes

    def __init__(self, taal):
        super().__init__()
        self.taal = taal
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        groepen = []
        browsers = detecteer_browsers()
        for b in browsers:
            if self._stop:
                return
            label = b["naam"]
            if b["profiel"]:
                label += " - " + b["profiel"]
            self.voortgang.emit(label)
            onderdelen = []
            for cat, paden in b["onderdelen"]:
                bytes_, aantal = 0, 0
                for p in paden:
                    bb, aa = pad_grootte(p)
                    bytes_ += bb
                    aantal += aa
                if bytes_ > 0 or aantal > 0:
                    onderdelen.append({"cat": cat, "bytes": bytes_,
                                       "aantal": aantal, "paden": paden})
            if onderdelen:
                groepen.append({"label": label, "soort": b["soort"],
                                "onderdelen": onderdelen})
        # systeem
        self.voortgang.emit("Windows / Systeem")
        sys_onderdelen = []
        for cat, paden in systeem_onderdelen():
            bytes_, aantal = 0, 0
            for p in paden:
                if cat == "temp" and os.path.isdir(p):
                    # alleen de inhoud, niet de map zelf
                    bb, aa = map_grootte(p)
                else:
                    bb, aa = pad_grootte(p)
                bytes_ += bb
                aantal += aa
            if bytes_ > 0 or aantal > 0:
                sys_onderdelen.append({"cat": cat, "bytes": bytes_,
                                       "aantal": aantal, "paden": paden})
        if sys_onderdelen:
            groepen.append({"label": "__systeem__", "soort": "systeem",
                            "onderdelen": sys_onderdelen})
        self.klaar.emit(groepen)


class BackupThread(QThread):
    voortgang = pyqtSignal(str)
    klaar = pyqtSignal(bool, str, int, int)   # ok, zip_pad/fout, bewaard, overgeslagen

    def __init__(self, doelmap):
        super().__init__()
        self.doelmap = doelmap
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            zip_pad, bewaard, overgeslagen = maak_backup(
                self.doelmap,
                voortgang=lambda p: self.voortgang.emit(os.path.basename(p)),
                gestopt=lambda: self._stop)
            self.klaar.emit(True, zip_pad, bewaard, overgeslagen)
        except Exception as e:
            self.klaar.emit(False, str(e), 0, 0)


class TerugzetThread(QThread):
    voortgang = pyqtSignal(str)
    klaar = pyqtSignal(bool, int, int)   # ok, teruggezet, mislukt

    def __init__(self, zip_pad):
        super().__init__()
        self.zip_pad = zip_pad
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            teruggezet, mislukt = zet_backup_terug(
                self.zip_pad,
                voortgang=lambda p: self.voortgang.emit(os.path.basename(p)),
                gestopt=lambda: self._stop)
            self.klaar.emit(True, teruggezet, mislukt)
        except Exception:
            self.klaar.emit(False, 0, 0)


class OpruimThread(QThread):
    voortgang = pyqtSignal(str)
    klaar = pyqtSignal(int, int, int, str)   # bytes_vrij, verwijderd, overgeslagen, logpad

    def __init__(self, onderdelen, witte_lijst, backup_eerst, backup_map):
        super().__init__()
        self.onderdelen = onderdelen
        self.witte_lijst = witte_lijst
        self.backup_eerst = backup_eerst
        self.backup_map = backup_map
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        # optioneel: eerst een back-up maken
        if self.backup_eerst:
            try:
                maak_backup(self.backup_map,
                            voortgang=lambda p: self.voortgang.emit(
                                "back-up: " + os.path.basename(p)),
                            gestopt=lambda: self._stop)
            except Exception:
                pass
        bytes_vrij, verwijderd, overgeslagen, logregels = maak_schoon(
            self.onderdelen, self.witte_lijst,
            voortgang=lambda c: self.voortgang.emit(c),
            gestopt=lambda: self._stop)
        logpad = os.path.join(BASIS, "laatste-opruiming.txt")
        try:
            with open(logpad, "w", encoding="utf-8") as f:
                f.write("DravePurge - logboek van de laatste opruiming\n")
                f.write(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n")
                f.write("Vrijgemaakt: %s  |  verwijderd: %d  |  overgeslagen: %d\n"
                        % (mensvriendelijke_grootte(bytes_vrij), verwijderd,
                           overgeslagen))
                f.write("=" * 60 + "\n")
                f.write("\n".join(logregels) + "\n")
        except Exception:
            logpad = ""
        self.klaar.emit(bytes_vrij, verwijderd, overgeslagen, logpad)


# ---------------------------------------------------------------------------
# Dialogen
# ---------------------------------------------------------------------------
SNELGIDS_NL = """
<h2>DravePurge - Snelgids</h2>
<p>DravePurge ruimt privacygevoelige rommel op je pc op: browser-cache,
cookies, geschiedenis, formuliergegevens en tijdelijke Windows-bestanden. Alles
blijft lokaal; er gaat niets naar internet.</p>
<h3>Zo werkt het</h3>
<ul>
<li><b>1. Scannen.</b> DravePurge zoekt zelf welke browsers op je pc staan
(Chrome, Edge, Brave, Firefox, Opera, Vivaldi, ...) en welke systeem-rommel er
is. Je ziet per categorie de grootte en het aantal bestanden.</li>
<li><b>2. Aanvinken.</b> Vink aan wat weg mag. <b>Cookies</b> en <b>ingevulde
formuliergegevens (autofill)</b> staan standaard <b>uit</b> voor de veiligheid -
die wil je meestal houden. Je kunt ze zelf aanvinken als je ze toch wilt wissen.</li>
<li><b>3. Opruimen.</b> Klik op <b>Opruimen</b>. Je krijgt eerst een overzicht
met wat er weggaat en hoeveel ruimte dat vrijmaakt, en je kunt (aanbevolen)
<b>eerst een back-up</b> laten maken. Pas na je bevestiging wordt er definitief
opgeruimd.</li>
</ul>
<h3>Je logins beschermen (witte lijst)</h3>
<p>Via <b>Witte lijst...</b> geef je de sites op waarvan de cookies behouden
moeten blijven (bijv. je mail of bank). Bij het opruimen blijven die cookies
staan, zodat je daar ingelogd blijft; alle andere cookies gaan weg. Zonder witte
lijst worden ALLE cookies gewist (en raak je overal uitgelogd).</p>
<h3>Vangnet: back-up &amp; terugzetten</h3>
<p>Met <b>Back-up maken</b> bewaar je je waardevolle browsergegevens (cookies,
geschiedenis, formuliergegevens, sessies) in een tijdgestempeld zip-bestand. Ging
er per ongeluk iets weg? Met <b>Terugzetten...</b> zet je het zo weer op z'n
plek.</p>
<p><b>Belangrijk:</b> sluit je browsers voordat je opruimt of terugzet - anders
zijn de bestanden vergrendeld en worden ze overgeslagen.</p>
<h3>Goed om te weten (wat je na het opruimen ziet)</h3>
<ul>
<li><b>Cookies = een klein databasebestand.</b> Bij het opruimen worden de
cookies eruit gehaald, maar als er nog cookies van je witte lijst overblijven,
blijft het bestand bestaan (kleiner). Blijven er geen cookies over, dan
verdwijnt het bestand helemaal. Een regel die nog ~20 KB toont, is dus geleegd,
niet onaangeroerd.</li>
<li><b>Tijdelijke bestanden die "in gebruik" zijn, kunnen niet weg.</b> Windows
en draaiende programma's houden veel temp-bestanden open; die slaat DravePurge
veilig over. Er blijft daarom vaak een restje temp staan - dat is normaal, geen
enkele opruimer krijgt bestanden-in-gebruik weg.</li>
<li><b>Wil je de cache of cookies van een browser echt opruimen?</b> Sluit die
browser dan volledig af (ook het achtergrondproces / het pictogram rechtsonder
in de systeembalk), anders is alles vergrendeld.</li>
</ul>
<p>Na elke opruimbeurt schrijft DravePurge een logboek (<b>laatste-opruiming.txt</b>,
naast de app) met per onderdeel wat er is verwijderd of overgeslagen, en waarom.</p>
<h3>Is dit veilig?</h3>
<p>Ja. DravePurge werkt volledig <b>lokaal en offline</b>: het leest en verwijdert
alleen bestanden op je eigen pc en stuurt niets naar internet.</p>
<p>Toch kan je antivirus of Windows SmartScreen waarschuwen. Dat heeft twee
onschuldige oorzaken: het is een <b>nieuw, niet-ondertekend</b> programma
("onbekende uitgever"), en het <b>verwijdert bestanden en leest browsergegevens</b>
- gedrag waar virusscanners standaard op letten. Het is dus een vals alarm.</p>
<ul>
<li>SmartScreen ("Windows heeft uw pc beschermd"): klik op <b>Meer informatie</b>
en daarna <b>Toch uitvoeren</b>.</li>
<li>Blijft de antivirus moeilijk doen, dan kun je de map met DravePurge als
uitzondering toevoegen.</li>
<li>Voor extra gerustheid: maak eerst een <b>back-up</b> (dat kan de app zelf) -
dan kun je altijd terug.</li>
</ul>
<p>Donatie (vrijwillig): <b>paypal.me/roger076</b> &middot; Contact:
service@dravenlock.nl</p>
"""

SNELGIDS_EN = """
<h2>DravePurge - Quick guide</h2>
<p>DravePurge cleans up privacy-sensitive junk on your PC: browser cache,
cookies, history, form data and temporary Windows files. Everything stays local;
nothing goes online.</p>
<h3>How it works</h3>
<ul>
<li><b>1. Scan.</b> DravePurge detects which browsers are on your PC (Chrome,
Edge, Brave, Firefox, Opera, Vivaldi, ...) and which system junk exists. You see
per category the size and number of files.</li>
<li><b>2. Tick.</b> Tick what may go. <b>Cookies</b> and <b>filled-in form data
(autofill)</b> are <b>off</b> by default for safety - you usually want to keep
those. Tick them yourself if you do want to clear them.</li>
<li><b>3. Clean up.</b> Click <b>Clean up</b>. You first get an overview of what
will be removed and how much space it frees, and you can (recommended) have a
<b>backup made first</b>. Only after your confirmation is anything removed.</li>
</ul>
<h3>Protect your logins (whitelist)</h3>
<p>Via <b>Whitelist...</b> you list the sites whose cookies should be kept (e.g.
your mail or bank). During cleaning those cookies stay, so you remain logged in;
all other cookies are removed. Without a whitelist, ALL cookies are cleared (and
you are logged out everywhere).</p>
<h3>Safety net: backup &amp; restore</h3>
<p>Use <b>Make backup</b> to save your valuable browser data (cookies, history,
form data, sessions) into a timestamped zip. Did something get deleted by
accident? <b>Restore...</b> puts it back.</p>
<p><b>Important:</b> close your browsers before cleaning or restoring - otherwise
the files are locked and get skipped.</p>
<h3>Good to know (what you see after cleaning)</h3>
<ul>
<li><b>Cookies = a small database file.</b> Cleaning removes the cookies from
it, but if cookies from your whitelist remain, the file stays (smaller). If no
cookies remain, the file is removed entirely. So a row still showing ~20 KB has
been emptied, not left untouched.</li>
<li><b>Temporary files that are "in use" cannot be removed.</b> Windows and
running programs keep many temp files open; DravePurge safely skips those. Some
temp will therefore remain - that is normal, no cleaner can remove files in
use.</li>
<li><b>Want to really clear a browser's cache or cookies?</b> Close that browser
completely (including the background process / the icon in the system tray),
otherwise everything is locked.</li>
</ul>
<p>After every clean, DravePurge writes a log (<b>laatste-opruiming.txt</b>, next
to the app) listing per item what was removed or skipped, and why.</p>
<h3>Is this safe?</h3>
<p>Yes. DravePurge works entirely <b>locally and offline</b>: it only reads and
deletes files on your own PC and sends nothing to the internet.</p>
<p>Still, your antivirus or Windows SmartScreen may warn you. There are two
harmless reasons: it is a <b>new, unsigned</b> program ("unknown publisher"), and
it <b>deletes files and reads browser data</b> - behaviour that virus scanners
watch for by default. So it is a false alarm.</p>
<ul>
<li>SmartScreen ("Windows protected your PC"): click <b>More info</b> and then
<b>Run anyway</b>.</li>
<li>If the antivirus keeps blocking it, you can add the DravePurge folder as an
exception.</li>
<li>For extra peace of mind: make a <b>backup</b> first (the app can do this) -
then you can always go back.</li>
</ul>
<p>Donate (voluntary): <b>paypal.me/roger076</b> &middot; Contact:
service@dravenlock.nl</p>
"""


class SnelgidsDialoog(QDialog):
    def __init__(self, venster):
        super().__init__(venster)
        self.setWindowTitle(venster.t("snelgids"))
        self.resize(640, 560)
        lay = QVBoxLayout(self)
        br = QTextBrowser()
        br.setOpenExternalLinks(True)
        br.setHtml(SNELGIDS_NL if venster.taal == "nl" else SNELGIDS_EN)
        lay.addWidget(br)
        knop = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        knop.rejected.connect(self.reject)
        knop.accepted.connect(self.accept)
        lay.addWidget(knop)


class OverDialoog(QDialog):
    def __init__(self, venster):
        super().__init__(venster)
        self.setWindowTitle(venster.t("over"))
        self.resize(420, 240)
        lay = QVBoxLayout(self)
        tekst = QLabel(
            "<h2>%s</h2><p>v%s</p>"
            "<p>%s</p>"
            "<p>Lokaal, offline, toegankelijk &middot; donationware</p>"
            "<p>Donatie: <b>paypal.me/roger076</b><br>Contact: %s</p>"
            % (APP_NAAM, APP_VERSIE, venster.t("ondertitel"), CONTACT))
        tekst.setWordWrap(True)
        tekst.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        tekst.setOpenExternalLinks(True)
        lay.addWidget(tekst)
        knop = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        knop.rejected.connect(self.reject)
        lay.addWidget(knop)


class WitteLijstDialoog(QDialog):
    """Beheer van de cookie-witte-lijst: sites waarvan de cookies behouden blijven."""
    def __init__(self, venster):
        super().__init__(venster)
        self.v = venster
        self.setWindowTitle(venster.t("witte_lijst"))
        self.resize(440, 460)
        lay = QVBoxLayout(self)

        uitleg = QLabel(venster.t("witte_lijst_uitleg"))
        uitleg.setObjectName("uitleg")
        uitleg.setWordWrap(True)
        lay.addWidget(uitleg)

        invoer = QHBoxLayout()
        self.invoer = QLineEdit()
        self.invoer.setPlaceholderText(venster.t("domein_invoer"))
        self.invoer.returnPressed.connect(self._toevoegen)
        invoer.addWidget(self.invoer, 1)
        btn_toe = QPushButton(venster.t("toevoegen"))
        btn_toe.clicked.connect(self._toevoegen)
        invoer.addWidget(btn_toe)
        lay.addLayout(invoer)

        self.lijst = QListWidget()
        lay.addWidget(self.lijst, 1)
        for d in venster.cfg.get("cookie_witte_lijst", []):
            self.lijst.addItem(d)
        self._toon_leeg_hint()

        btn_verw = QPushButton(venster.t("verwijderen"))
        btn_verw.clicked.connect(self._verwijderen)
        lay.addWidget(btn_verw)

        knoppen = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                   QDialogButtonBox.StandardButton.Cancel)
        knoppen.button(QDialogButtonBox.StandardButton.Save).setText(
            venster.t("opslaan"))
        knoppen.button(QDialogButtonBox.StandardButton.Cancel).setText(
            venster.t("annuleren"))
        knoppen.accepted.connect(self._opslaan)
        knoppen.rejected.connect(self.reject)
        lay.addWidget(knoppen)

    def _toon_leeg_hint(self):
        # placeholder-tekst tonen als de lijst leeg is
        if self.lijst.count() == 0:
            self.lijst.setToolTip(self.v.t("witte_lijst_leeg"))
        else:
            self.lijst.setToolTip("")

    def _huidige_domeinen(self):
        return [self.lijst.item(i).text() for i in range(self.lijst.count())]

    def _toevoegen(self):
        d = normaliseer_domein(self.invoer.text())
        if d and d not in self._huidige_domeinen():
            self.lijst.addItem(d)
        self.invoer.clear()
        self._toon_leeg_hint()

    def _verwijderen(self):
        for item in self.lijst.selectedItems():
            self.lijst.takeItem(self.lijst.row(item))
        self._toon_leeg_hint()

    def _opslaan(self):
        self.v.cfg["cookie_witte_lijst"] = self._huidige_domeinen()
        bewaar_config(self.v.cfg)
        self.accept()


class TerugzetDialoog(QDialog):
    """Kies een back-up en zet de bestanden terug op hun plek."""
    def __init__(self, venster):
        super().__init__(venster)
        self.v = venster
        self.terugzet_thread = None
        self.setWindowTitle(venster.t("terugzet_titel"))
        self.resize(560, 440)
        lay = QVBoxLayout(self)

        uitleg = QLabel(venster.t("terugzet_uitleg"))
        uitleg.setObjectName("uitleg")
        uitleg.setWordWrap(True)
        lay.addWidget(uitleg)

        self.lijst = QListWidget()
        lay.addWidget(self.lijst, 1)
        self.backups = lees_backups(backup_map_pad(venster.cfg))
        if self.backups:
            for b in self.backups:
                self.lijst.addItem(venster.t("backup_item").format(
                    datum=b["datum"] or b["naam"], n=b["aantal"],
                    grootte=mensvriendelijke_grootte(b["grootte"])))
            self.lijst.setCurrentRow(0)
        else:
            self.lijst.addItem(venster.t("geen_backups"))
            self.lijst.setEnabled(False)

        self.balk = QProgressBar()
        self.balk.setRange(0, 0)
        self.balk.setVisible(False)
        lay.addWidget(self.balk)

        rij = QHBoxLayout()
        self.btn_map = QPushButton(venster.t("map_openen"))
        self.btn_map.clicked.connect(self._map_openen)
        rij.addWidget(self.btn_map)
        rij.addStretch(1)
        self.btn_terug = QPushButton(venster.t("terugzetten"))
        self.btn_terug.setObjectName("primair")
        self.btn_terug.setEnabled(bool(self.backups))
        self.btn_terug.clicked.connect(self._start_terugzetten)
        rij.addWidget(self.btn_terug)
        btn_sluit = QPushButton(venster.t("annuleren"))
        btn_sluit.clicked.connect(self.reject)
        rij.addWidget(btn_sluit)
        lay.addLayout(rij)

    def _map_openen(self):
        map_pad = backup_map_pad(self.v.cfg)
        os.makedirs(map_pad, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(map_pad))

    def _start_terugzetten(self):
        rij = self.lijst.currentRow()
        if rij < 0 or rij >= len(self.backups):
            return
        antwoord = QMessageBox.question(
            self, self.v.t("terugzet_titel"), self.v.t("terugzet_bevestig"))
        if antwoord != QMessageBox.StandardButton.Yes:
            return
        zip_pad = self.backups[rij]["pad"]
        self.btn_terug.setEnabled(False)
        self.balk.setVisible(True)
        self.terugzet_thread = TerugzetThread(zip_pad)
        self.terugzet_thread.klaar.connect(self._terugzet_klaar)
        self.terugzet_thread.start()

    def _terugzet_klaar(self, ok, teruggezet, mislukt):
        self.balk.setVisible(False)
        self.btn_terug.setEnabled(True)
        if mislukt:
            tekst = self.v.t("terugzet_klaar_mislukt").format(n=teruggezet, m=mislukt)
        else:
            tekst = self.v.t("terugzet_klaar").format(n=teruggezet)
        QMessageBox.information(self, self.v.t("terugzet_titel"), tekst)


class OpruimenDialoog(QDialog):
    """Bevestiging vooraf: overzicht van wat wordt opgeruimd, optie om eerst een
    back-up te maken, en waarschuwingen (witte lijst / browsers sluiten)."""
    def __init__(self, venster, onderdelen):
        super().__init__(venster)
        self.v = venster
        self.setWindowTitle(venster.t("opruim_titel"))
        self.resize(520, 520)
        lay = QVBoxLayout(self)

        kop = QLabel(venster.t("opruim_overzicht"))
        kop.setObjectName("uitleg")
        kop.setWordWrap(True)
        lay.addWidget(kop)

        # overzicht per categorie (opgeteld)
        agg = {}
        totaal = 0
        cookies_erbij = False
        for o in onderdelen:
            agg[o["cat"]] = agg.get(o["cat"], 0) + o.get("bytes", 0)
            totaal += o.get("bytes", 0)
            if o["cat"] == "cookies":
                cookies_erbij = True
        regels = []
        for cat, b in agg.items():
            regels.append("&bull; %s &mdash; %s" %
                          (venster.t(cat), mensvriendelijke_grootte(b)))
        overzicht = QTextBrowser()
        overzicht.setHtml("<br>".join(regels) + "<br><br><b>" +
                          venster.t("opruim_totaal").format(
                              grootte=mensvriendelijke_grootte(totaal),
                              n=len(agg)) + "</b>")
        overzicht.setMaximumHeight(180)
        lay.addWidget(overzicht)

        # cookie-melding
        if cookies_erbij:
            wl = venster.cfg.get("cookie_witte_lijst", [])
            if wl:
                m = QLabel(venster.t("opruim_cookies_witlijst").format(
                    sites=", ".join(wl)))
                m.setObjectName("uitleg")
            else:
                m = QLabel(venster.t("opruim_cookies_alles"))
                m.setObjectName("waarschuwing")
            m.setWordWrap(True)
            lay.addWidget(m)

        # browser-waarschuwing
        waarsch = venster.t("opruim_sluit_browser")
        draait = draaiende_browsers()
        if draait:
            waarsch += "\n" + venster.t("opruim_draait").format(
                namen=", ".join(draait))
        wl2 = QLabel(waarsch)
        wl2.setObjectName("waarschuwing")
        wl2.setWordWrap(True)
        lay.addWidget(wl2)

        # eerst back-up
        self.chk_backup = QCheckBox(venster.t("opruim_backup_eerst"))
        self.chk_backup.setChecked(True)
        lay.addWidget(self.chk_backup)

        lay.addStretch(1)
        rij = QHBoxLayout()
        rij.addStretch(1)
        btn_ok = QPushButton(venster.t("opruim_knop"))
        btn_ok.setObjectName("gevaar")
        btn_ok.clicked.connect(self.accept)
        rij.addWidget(btn_ok)
        btn_an = QPushButton(venster.t("annuleren"))
        btn_an.clicked.connect(self.reject)
        rij.addWidget(btn_an)
        lay.addLayout(rij)

    def backup_eerst(self):
        return self.chk_backup.isChecked()


class WelkomDialoog(QDialog):
    """Welkomstvenster met duidelijke waarschuwing en de aanbevolen eerste stappen."""
    def __init__(self, venster):
        super().__init__(venster)
        self.v = venster
        self.backup_thread = None
        self.setWindowTitle(venster.t("welkom_titel"))
        self.resize(560, 600)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        # kop met logo
        kop = QHBoxLayout()
        lg = QLabel()
        p = os.path.join(BASIS, "logo.png")
        if os.path.exists(p):
            pm = QPixmap(p)
            if not pm.isNull():
                lg.setPixmap(pm.scaled(QSize(56, 56),
                             Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation))
        kop.addWidget(lg)
        titel = QLabel(venster.t("welkom_titel"))
        titel.setObjectName("titel")
        kop.addWidget(titel)
        kop.addStretch(1)
        lay.addLayout(kop)

        intro = QLabel(venster.t("welkom_intro"))
        intro.setWordWrap(True)
        lay.addWidget(intro)

        waarsch = QLabel(venster.t("welkom_waarschuwing"))
        waarsch.setObjectName("waarschuwing")
        waarsch.setWordWrap(True)
        lay.addWidget(waarsch)

        kop2 = QLabel(venster.t("welkom_stappen_kop"))
        kop2.setObjectName("uitleg")
        kop2.setWordWrap(True)
        lay.addWidget(kop2)
        for sleutel in ("welkom_stap1", "welkom_stap2", "welkom_stap3"):
            st = QLabel(venster.t(sleutel))
            st.setWordWrap(True)
            lay.addWidget(st)

        # actieknoppen voor de drie stappen
        acties = QHBoxLayout()
        b1 = QPushButton(venster.t("welkom_snelgids"))
        b1.clicked.connect(lambda: SnelgidsDialoog(self.v).exec())
        acties.addWidget(b1)
        b2 = QPushButton(venster.t("welkom_witlijst"))
        b2.clicked.connect(lambda: WitteLijstDialoog(self.v).exec())
        acties.addWidget(b2)
        self.b3 = QPushButton(venster.t("welkom_backup"))
        self.b3.clicked.connect(self._backup)
        acties.addWidget(self.b3)
        lay.addLayout(acties)

        daarna = QLabel(venster.t("welkom_daarna"))
        daarna.setObjectName("uitleg")
        daarna.setWordWrap(True)
        lay.addWidget(daarna)

        veilig = QLabel(venster.t("welkom_veilig"))
        veilig.setObjectName("uitleg")
        veilig.setWordWrap(True)
        lay.addWidget(veilig)

        lay.addStretch(1)
        self.chk = QCheckBox(venster.t("welkom_niet_meer"))
        lay.addWidget(self.chk)
        rij = QHBoxLayout()
        rij.addStretch(1)
        start = QPushButton(venster.t("welkom_start"))
        start.setObjectName("primair")
        start.clicked.connect(self.accept)
        rij.addWidget(start)
        lay.addLayout(rij)

    def _backup(self):
        if self.backup_thread and self.backup_thread.isRunning():
            return
        self.b3.setEnabled(False)
        self.b3.setText(self.v.t("backup_bezig"))
        self.backup_thread = BackupThread(backup_map_pad(self.v.cfg))
        self.backup_thread.klaar.connect(self._backup_klaar)
        self.backup_thread.start()

    def _backup_klaar(self, ok, pad_of_fout, bewaard, overgeslagen):
        self.b3.setEnabled(True)
        self.b3.setText(self.v.t("welkom_backup"))
        if not ok:
            QMessageBox.warning(self, APP_NAAM,
                                self.v.t("backup_mislukt").format(fout=pad_of_fout))
            return
        if overgeslagen:
            tekst = self.v.t("backup_klaar_over").format(n=bewaard, over=overgeslagen)
        else:
            tekst = self.v.t("backup_klaar").format(n=bewaard)
        QMessageBox.information(self, APP_NAAM, tekst + "\n\n" + pad_of_fout)

    def accept(self):
        if self.chk.isChecked():
            self.v.cfg["toon_welkom"] = False
            bewaar_config(self.v.cfg)
        super().accept()


class InstellingenDialoog(QDialog):
    def __init__(self, venster):
        super().__init__(venster)
        self.v = venster
        self.setWindowTitle(venster.t("instellingen"))
        self.resize(360, 160)
        lay = QFormLayout(self)
        self.taal_box = QComboBox()
        self.taal_box.addItem(venster.t("taal_auto"), "auto")
        self.taal_box.addItem("Nederlands", "nl")
        self.taal_box.addItem("English", "en")
        huidig = venster.cfg_taal
        idx = {"auto": 0, "nl": 1, "en": 2}.get(huidig, 0)
        self.taal_box.setCurrentIndex(idx)
        lay.addRow(venster.t("taal"), self.taal_box)
        knop = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        knop.accepted.connect(self._opslaan)
        knop.rejected.connect(self.reject)
        lay.addRow(knop)

    def _opslaan(self):
        self.v.cfg_taal = self.taal_box.currentData()
        self.v.taal = (self.v.cfg_taal if self.v.cfg_taal in ("nl", "en")
                       else detecteer_taal())
        self.accept()


# ---------------------------------------------------------------------------
# Hoofdvenster
# ---------------------------------------------------------------------------
class Hoofdvenster(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = laad_config()
        self.cfg_taal = self.cfg.get("taal", "auto")
        self.taal = (self.cfg_taal if self.cfg_taal in ("nl", "en")
                     else detecteer_taal())
        self.scan_thread = None
        self.groepen = []
        self.setWindowTitle("%s  v%s" % (APP_NAAM, APP_VERSIE))
        self.resize(820, 620)
        self._zet_icoon()
        self._bouw_ui()
        self.pas_stijl_toe()

    def t(self, sleutel):
        return TEKST[self.taal].get(sleutel, sleutel)

    def _zet_icoon(self):
        p = os.path.join(BASIS, "logo.png")
        if os.path.exists(p):
            self.setWindowIcon(QIcon(p))

    # ---- UI ----
    def _bouw_ui(self):
        centraal = QWidget()
        self.setCentralWidget(centraal)
        lay = QVBoxLayout(centraal)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        # kop
        kop = QHBoxLayout()
        logo = QLabel()
        p = os.path.join(BASIS, "logo.png")
        if os.path.exists(p):
            pm = QPixmap(p)
            if not pm.isNull():
                logo.setPixmap(pm.scaled(QSize(48, 48),
                               Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation))
        kop.addWidget(logo)
        titels = QVBoxLayout()
        t1 = QLabel(self.t("titel"))
        t1.setObjectName("titel")
        t2 = QLabel(self.t("ondertitel"))
        t2.setObjectName("ondertitel")
        titels.addWidget(t1)
        titels.addWidget(t2)
        kop.addLayout(titels)
        kop.addStretch(1)
        lay.addLayout(kop)

        # knoppenbalk
        knoppen = QHBoxLayout()
        self.btn_scan = QPushButton(self.t("scannen"))
        self.btn_scan.setObjectName("primair")
        self.btn_scan.clicked.connect(self.start_scan)
        knoppen.addWidget(self.btn_scan)
        self.btn_opruimen = QPushButton(self.t("opruimen"))
        self.btn_opruimen.setObjectName("gevaar")
        self.btn_opruimen.clicked.connect(self._opruimen)
        knoppen.addWidget(self.btn_opruimen)
        knoppen.addStretch(1)
        self.btn_backup = QPushButton(self.t("backup_maken"))
        self.btn_backup.clicked.connect(self.start_backup)
        knoppen.addWidget(self.btn_backup)
        self.btn_terugzet = QPushButton(self.t("terugzetten"))
        self.btn_terugzet.clicked.connect(self._terugzetten)
        knoppen.addWidget(self.btn_terugzet)
        self.btn_witlijst = QPushButton(self.t("witte_lijst_knop"))
        self.btn_witlijst.clicked.connect(self._witte_lijst)
        knoppen.addWidget(self.btn_witlijst)
        lay.addLayout(knoppen)

        # informatie-strook v0.1
        self.info = QLabel(self.t("v01_info"))
        self.info.setObjectName("infostrook")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)

        # boom met resultaten
        self.boom = QTreeWidget()
        self.boom.setColumnCount(3)
        self.boom.setHeaderLabels([self.t("kolom_item"), self.t("kolom_grootte"),
                                   self.t("kolom_aantal")])
        self.boom.setRootIsDecorated(True)
        self.boom.setAlternatingRowColors(False)
        self.boom.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        hdr = self.boom.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.boom, 1)

        # voortgang
        self.balk = QProgressBar()
        self.balk.setRange(0, 0)
        self.balk.setVisible(False)
        lay.addWidget(self.balk)

        # statusbalk + donatie
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status_links = QLabel("")
        self.status.addWidget(self.status_links, 1)
        self.btn_donatie = QPushButton(" \u2665 " + self.t("donatie"))
        self.btn_donatie.setObjectName("donatie")
        self.btn_donatie.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_donatie.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(DONATIE_URL)))
        self.status.addPermanentWidget(self.btn_donatie)

        self._bouw_menu()

    def _bouw_menu(self):
        mb = self.menuBar()
        m_best = mb.addMenu(self.t("instellingen"))
        a_inst = QAction(self.t("instellingen"), self)
        a_inst.triggered.connect(self._instellingen)
        m_best.addAction(a_inst)
        a_wit = QAction(self.t("witte_lijst") + "...", self)
        a_wit.triggered.connect(self._witte_lijst)
        m_best.addAction(a_wit)
        m_best.addSeparator()
        a_sluit = QAction(self.t("sluiten"), self)
        a_sluit.setShortcut("Ctrl+Q")
        a_sluit.triggered.connect(self.close)
        m_best.addAction(a_sluit)

        m_help = mb.addMenu(self.t("menu_help"))
        a_gids = QAction(self.t("snelgids"), self)
        a_gids.setShortcut("F1")
        a_gids.triggered.connect(lambda: SnelgidsDialoog(self).exec())
        m_help.addAction(a_gids)
        a_welkom = QAction(self.t("welkom_menu"), self)
        a_welkom.triggered.connect(lambda: WelkomDialoog(self).exec())
        m_help.addAction(a_welkom)
        a_don = QAction("\u2665 " + self.t("donatie"), self)
        a_don.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(DONATIE_URL)))
        m_help.addAction(a_don)
        a_over = QAction(self.t("over"), self)
        a_over.triggered.connect(lambda: OverDialoog(self).exec())
        m_help.addAction(a_over)

    # ---- scan ----
    def start_scan(self):
        if self.scan_thread and self.scan_thread.isRunning():
            return
        self.boom.clear()
        self.btn_scan.setEnabled(False)
        self.balk.setVisible(True)
        self.status_links.setText(self.t("bezig"))
        self.scan_thread = ScanThread(self.taal)
        self.scan_thread.voortgang.connect(self._scan_voortgang)
        self.scan_thread.klaar.connect(self._scan_klaar)
        self.scan_thread.start()

    def _scan_voortgang(self, label):
        if label == "Windows / Systeem":
            label = self.t("systeem")
        self.status_links.setText(self.t("bezig") + "  (" + label + ")")

    def _scan_klaar(self, groepen):
        self.groepen = groepen
        self.balk.setVisible(False)
        self.btn_scan.setEnabled(True)
        totaal = 0
        for g in groepen:
            label = self.t("systeem") if g["label"] == "__systeem__" else g["label"]
            groep_bytes = sum(o["bytes"] for o in g["onderdelen"])
            groep_aantal = sum(o["aantal"] for o in g["onderdelen"])
            totaal += groep_bytes
            ouder = QTreeWidgetItem([label, mensvriendelijke_grootte(groep_bytes),
                                     str(groep_aantal)])
            ouder.setFlags(ouder.flags() | Qt.ItemFlag.ItemIsUserCheckable |
                           Qt.ItemFlag.ItemIsAutoTristate)
            ouder.setCheckState(0, Qt.CheckState.Checked)
            f = ouder.font(0)
            f.setBold(True)
            ouder.setFont(0, f)
            for o in g["onderdelen"]:
                uit = o["cat"] in STANDAARD_UIT
                label_kind = self.t(o["cat"])
                if uit:
                    label_kind += self.t(SUFFIX_SLEUTEL[o["cat"]])
                kind = QTreeWidgetItem([label_kind,
                                        mensvriendelijke_grootte(o["bytes"]),
                                        str(o["aantal"])])
                kind.setFlags(kind.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                kind.setCheckState(0, Qt.CheckState.Unchecked if uit
                                   else Qt.CheckState.Checked)
                kind.setData(0, Qt.ItemDataRole.UserRole,
                             {"cat": o["cat"], "soort": g["soort"],
                              "paden": o["paden"], "bytes": o["bytes"],
                              "label": label})
                ouder.addChild(kind)
            self.boom.addTopLevelItem(ouder)
            ouder.setExpanded(True)
        if groepen:
            self.status_links.setText(
                self.t("klaar_scan").format(grootte=mensvriendelijke_grootte(totaal)))
        else:
            self.status_links.setText(self.t("geen_browsers"))

    def _witte_lijst(self):
        WitteLijstDialoog(self).exec()

    # ---- back-up ----
    def start_backup(self):
        if self.scan_thread and self.scan_thread.isRunning():
            return
        if getattr(self, "backup_thread", None) and self.backup_thread.isRunning():
            return
        self.btn_backup.setEnabled(False)
        self.balk.setVisible(True)
        self.status_links.setText(self.t("backup_bezig"))
        self.backup_thread = BackupThread(backup_map_pad(self.cfg))
        self.backup_thread.voortgang.connect(
            lambda naam: self.status_links.setText(self.t("backup_bezig") + "  " + naam))
        self.backup_thread.klaar.connect(self._backup_klaar)
        self.backup_thread.start()

    def _backup_klaar(self, ok, pad_of_fout, bewaard, overgeslagen):
        self.balk.setVisible(False)
        self.btn_backup.setEnabled(True)
        if not ok:
            self.status_links.setText("")
            QMessageBox.warning(self, APP_NAAM,
                                self.t("backup_mislukt").format(fout=pad_of_fout))
            return
        if overgeslagen:
            tekst = self.t("backup_klaar_over").format(n=bewaard, over=overgeslagen)
        else:
            tekst = self.t("backup_klaar").format(n=bewaard)
        self.status_links.setText(tekst)
        QMessageBox.information(self, APP_NAAM,
                                tekst + "\n\n" + pad_of_fout + "\n\n" +
                                self.t("backup_sluit_tip"))

    def _terugzetten(self):
        TerugzetDialoog(self).exec()

    # ---- opruimen (v0.2) ----
    def verzamel_aangevinkt(self):
        uit = []
        for i in range(self.boom.topLevelItemCount()):
            ouder = self.boom.topLevelItem(i)
            for j in range(ouder.childCount()):
                k = ouder.child(j)
                if k.checkState(0) == Qt.CheckState.Checked:
                    data = k.data(0, Qt.ItemDataRole.UserRole)
                    if data:
                        uit.append(data)
        return uit

    def _opruimen(self):
        onderdelen = self.verzamel_aangevinkt()
        if not onderdelen:
            QMessageBox.information(self, APP_NAAM, self.t("opruim_niets"))
            return
        d = OpruimenDialoog(self, onderdelen)
        if d.exec():
            self.start_opruimen(onderdelen, d.backup_eerst())

    def start_opruimen(self, onderdelen, backup_eerst):
        self.btn_opruimen.setEnabled(False)
        self.btn_scan.setEnabled(False)
        self.balk.setVisible(True)
        self.status_links.setText(self.t("opruim_bezig"))
        wl = self.cfg.get("cookie_witte_lijst", [])
        self.opruim_thread = OpruimThread(onderdelen, wl, backup_eerst,
                                          backup_map_pad(self.cfg))
        self.opruim_thread.voortgang.connect(
            lambda c: self.status_links.setText(self.t("opruim_bezig") + "  " + self.t(c)))
        self.opruim_thread.klaar.connect(self._opruim_klaar)
        self.opruim_thread.start()

    def _opruim_klaar(self, bytes_vrij, verwijderd, overgeslagen, logpad):
        self.balk.setVisible(False)
        self.btn_opruimen.setEnabled(True)
        self.btn_scan.setEnabled(True)
        g = mensvriendelijke_grootte(bytes_vrij)
        log_regel = ("\n\n" + self.t("opruim_log").format(pad=logpad)) if logpad else ""
        # Niets verwijderd terwijl er wel iets is overgeslagen = vergrendeld of
        # een ander probleem. Toon de reden en open meteen het logboek.
        if verwijderd == 0 and overgeslagen > 0:
            self.status_links.setText(self.t("opruim_niets_kort"))
            QMessageBox.warning(
                self, APP_NAAM,
                self.t("opruim_niets_vrij").format(over=overgeslagen) + log_regel)
            if logpad:
                QDesktopServices.openUrl(QUrl.fromLocalFile(logpad))
            self.start_scan()
            return
        if overgeslagen:
            tekst = self.t("opruim_klaar_over").format(grootte=g, n=verwijderd,
                                                       over=overgeslagen)
        else:
            tekst = self.t("opruim_klaar").format(grootte=g, n=verwijderd)
        self.status_links.setText(tekst)
        QMessageBox.information(self, APP_NAAM, tekst + log_regel)
        self.start_scan()   # opnieuw scannen om het resultaat te tonen

    # ---- instellingen ----
    def _instellingen(self):
        d = InstellingenDialoog(self)
        if d.exec():
            self.cfg["taal"] = self.cfg_taal
            bewaar_config(self.cfg)
            self._hervertaal()

    def _hervertaal(self):
        self.btn_scan.setText(self.t("scannen"))
        self.btn_opruimen.setText(self.t("opruimen"))
        self.btn_backup.setText(self.t("backup_maken"))
        self.btn_terugzet.setText(self.t("terugzetten"))
        self.btn_witlijst.setText(self.t("witte_lijst_knop"))
        self.info.setText(self.t("v01_info"))
        self.btn_donatie.setText(" \u2665 " + self.t("donatie"))
        self.boom.setHeaderLabels([self.t("kolom_item"), self.t("kolom_grootte"),
                                   self.t("kolom_aantal")])
        self.menuBar().clear()
        self._bouw_menu()
        # boom opnieuw opbouwen met vertaalde labels
        if self.groepen:
            self._scan_klaar(self.groepen)

    # ---- stijl ----
    def pas_stijl_toe(self):
        self.setStyleSheet(STIJL)
        f = QFont()
        f.setPointSize(11)
        app = QApplication.instance()
        app.setFont(f)
        pal = QPalette()
        rol = QPalette.ColorRole
        pal.setColor(rol.Window, QColor(BG))
        pal.setColor(rol.WindowText, QColor(TEXT))
        pal.setColor(rol.Base, QColor(BG))
        pal.setColor(rol.AlternateBase, QColor(PANEL))
        pal.setColor(rol.Text, QColor(TEXT))
        pal.setColor(rol.Button, QColor(PANEL2))
        pal.setColor(rol.ButtonText, QColor(TEXT))
        pal.setColor(rol.Highlight, QColor(ACCENT))
        pal.setColor(rol.HighlightedText, QColor("#0e0e11"))
        app.setPalette(pal)

    def closeEvent(self, e):
        for naam in ("scan_thread", "backup_thread", "opruim_thread"):
            t = getattr(self, naam, None)
            if t and t.isRunning():
                t.stop()
                t.wait(1500)
        super().closeEvent(e)


STIJL = """
* { outline: none; }
QWidget { background: %(bg)s; color: %(text)s; font-size: 11pt; }
QLabel#titel { font-size: 18pt; font-weight: bold; color: %(text)s; }
QLabel#ondertitel { color: %(muted)s; }
QLabel#infostrook {
    background: %(panel2)s; color: %(warn)s; border: 1px solid %(line)s;
    border-radius: 8px; padding: 8px 10px;
}
QMenuBar { background: %(panel)s; color: %(text)s; }
QMenuBar::item:selected { background: %(accent_dim)s; color: #ffffff; }
QMenu { background: %(panel2)s; color: %(text)s; border: 1px solid %(line)s; }
QMenu::item:selected { background: %(accent)s; color: #0e0e11; }
QPushButton {
    background: %(panel2)s; color: %(text)s; border: 1px solid %(line)s;
    border-radius: 8px; padding: 8px 16px;
}
QPushButton:hover { border-color: %(accent)s; }
QPushButton:disabled { color: %(muted)s; }
QPushButton#primair {
    background: %(accent)s; color: #0e0e11; font-weight: bold; border: none;
}
QPushButton#primair:hover { background: #84b4e0; }
QPushButton#gevaar {
    background: %(warn)s; color: #0e0e11; font-weight: bold; border: none;
}
QPushButton#gevaar:hover { background: #e0a085; }
QLabel#waarschuwing {
    background: %(panel2)s; color: %(warn)s; border: 1px solid %(line)s;
    border-radius: 8px; padding: 8px 10px;
}
QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 18px; height: 18px; border: 1px solid %(accent)s;
    border-radius: 4px; background: %(panel2)s;
}
QCheckBox::indicator:checked {
    background: %(accent)s; border-color: %(accent)s;
}
QPushButton#donatie {
    background: %(accent)s; color: #0e0e11; font-weight: bold; border: none;
    border-radius: 8px; padding: 6px 14px;
}
QTreeWidget {
    background: %(panel)s; color: %(text)s; border: 1px solid %(line)s;
    border-radius: 8px;
}
QTreeWidget::item { padding: 4px 2px; }
QTreeWidget::item:hover { background: %(panel2)s; }
QHeaderView::section {
    background: %(panel2)s; color: %(muted)s; border: none;
    border-bottom: 1px solid %(line)s; padding: 6px 8px;
}
QProgressBar {
    background: %(panel2)s; border: 1px solid %(line)s; border-radius: 6px;
    height: 14px; text-align: center;
}
QProgressBar::chunk { background: %(accent)s; border-radius: 5px; }
QStatusBar { background: %(panel)s; color: %(muted)s; }
QComboBox {
    background: %(panel2)s; color: %(text)s; border: 1px solid %(line)s;
    border-radius: 6px; padding: 5px 8px;
}
QComboBox QAbstractItemView {
    background: %(panel2)s; color: %(text)s;
    selection-background-color: %(accent)s; selection-color: #0e0e11;
}
QTextBrowser {
    background: %(bg)s; color: %(text)s; border: 1px solid %(line)s;
    border-radius: 8px;
}
QLabel#uitleg { color: %(muted)s; padding: 2px 0 6px 0; }
QListWidget {
    background: %(panel)s; color: %(text)s; border: 1px solid %(line)s;
    border-radius: 8px; padding: 4px;
}
QListWidget::item { padding: 6px 6px; border-radius: 5px; }
QListWidget::item:selected { background: %(accent)s; color: #0e0e11; }
QLineEdit {
    background: %(panel2)s; color: %(text)s; border: 1px solid %(line)s;
    border-radius: 6px; padding: 6px 8px;
    selection-background-color: %(accent)s; selection-color: #0e0e11;
}
QLineEdit:focus { border-color: %(accent)s; }""" % {
    "bg": BG, "panel": PANEL, "panel2": PANEL2, "text": TEXT, "muted": MUTED,
    "accent": ACCENT, "accent_dim": ACCENT_DIM, "line": LINE, "warn": WAARSCHUW,
}


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAAM)
    v = Hoofdvenster()
    v.show()
    if v.cfg.get("toon_welkom", True):
        QTimer.singleShot(0, lambda: WelkomDialoog(v).exec())
    try:  # Dravenlock: stille update-check (uit te zetten; Ctrl+Shift+U = met de hand)
        import drave_update
        drave_update.start(v, 'DravePurge', APP_VERSIE)
    except Exception:
        pass
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
