"""LE REGISTRE DES CONVENTIONS — lecture, controles, et le cliquet.

Le registre lui-meme est `V3/conventions.yaml` ; ce module sait le lire et le
VERIFIER contre la donnee. `V3/tests/test_conventions.py` n'est que le lanceur.

POURQUOI CE MODULE EXISTE. Le 14/09/2026, `d_vwap_w` a ete calcule sans
negation alors que tout le depot suit `dist_X = (niveau - prix) / tick`. B1p a
dit SHORT quand le prix etait AU-DESSUS de sa VWAP semaine, sur 100 % des
barres. La verification ecrite le meme matin comparait la distribution de la
VALEUR ABSOLUE a celle publiee : un controle d'amplitude ne peut pas voir une
direction.

Le meme jour, l'audit lui-meme s'est trompe QUATRE fois, toujours de la meme
facon — comparer a la mauvaise reference :

  - CVD cumule a travers les journees au lieu de par session (54,8 % au lieu
    de 100 %) ;
  - ATR sur barres d'une minute confronte a un true range de quinze minutes ;
  - moyenne agregee la ou il fallait regarder jour par jour ;
  - une premiere version du controle qui jugeait sur UN SEUL jour, tombee sur
    le 7 septembre, ferie americain : seance atrophiee, true range minuscule,
    `atr` declare hors plage pour rien.

Aucune de ces quatre erreurs n'etait une donnee qui ment.

D'OU LA FORME RETENUE. Chaque controle travaille JOUR PAR JOUR, sur plusieurs
jours, et n'agrege que ce qui est agregeable. Le cumul, la pente et la
constance d'un niveau n'ont de sens qu'a l'interieur d'une seance ; les
melanger fabrique exactement l'erreur que ce fichier existe pour interdire.

Aucun devenir n'est lu : on ne compare que des colonnes d'entree entre elles.
"""
from __future__ import annotations

import ast
import glob
import os

import pandas as pd
import yaml

from CORE.bot_terminal import charger_jour
from CORE.research.hypothesis_runner import injecter_recalculs
from V3.campagne import COLS_RECALC, chauffe_1min, jours_disponibles

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
REGISTRE = os.path.join(RACINE, "V3", "conventions.yaml")
TICK = 0.25
PART = 0.98        # quasi-unanimite : niveau et cloture peuvent etre egaux
N_MIN = 50         # en dessous, le controle ne prouve rien et doit le DIRE
N_JOURS = 8        # plusieurs jours : un seul peut etre ferie
JOUR_1 = "20260908"


def charger(chemin=REGISTRE):
    """Rend (colonnes, familles). Un registre vide est une ERREUR de lecture,
    pas un registre sans regle : l'appelant doit le traiter comme tel."""
    reg = yaml.safe_load(open(chemin, encoding="utf-8")) or {}
    return reg.get("colonnes") or {}, reg.get("familles") or {}


def lots(sym, n=N_JOURS):
    """Jusqu'a `n` jours d'ARCHIVE, chacun garde SEPARE : (jour, 15 min, 1 min).

    Separes, et non concatenes : le cumul et la pente n'ont de sens qu'a
    l'interieur d'une seance. Les jours de campagne sont exclus — ce module
    n'a aucune raison de les ouvrir.
    """
    out = []
    for jour in reversed([j for j in jours_disponibles(sym) if j < JOUR_1]):
        if len(out) >= n:
            break
        df, brut = charger_jour(sym, jour, 15, avec_1min=True)
        if df.empty or brut.empty:
            continue
        if not all(c in brut.columns for c in COLS_RECALC):
            continue
        out.append((jour, injecter_recalculs(
            pd.concat(chauffe_1min(sym, jour) + [brut[COLS_RECALC]],
                      ignore_index=True), df, minutes=15), brut))
    return out


def _signe_attendu(e, familles):
    fam = familles.get(e.get("famille"), {})
    return e.get("signe") or fam.get("signe") or "aucun"


def _verdict(ok_tot, n_tot, attendu):
    if n_tot < N_MIN:
        return None, "seulement %d barres" % n_tot
    a = ok_tot / n_tot
    ok = a <= 1 - PART if attendu == "inverse" else a >= PART
    return ok, "accord %.2f %% sur %d barres (attendu %s)" % (100 * a, n_tot, attendu)


# --- les controles : chacun recoit la LISTE des jours ----------------------

def c_jumeau(nom, e, fam, jours):
    """`close > niveau` coincide-t-il avec `dist > 0` ?"""
    ok_tot = n_tot = 0
    for _j, _dfe, brut in jours:
        if nom not in brut.columns or e["jumeau"] not in brut.columns:
            continue
        s = brut.dropna(subset=["close", nom, e["jumeau"]])
        s = s[s["close"] != s[e["jumeau"]]]
        ok_tot += int(((s["close"] > s[e["jumeau"]]) == (s[nom] > 0)).sum())
        n_tot += len(s)
    return _verdict(ok_tot, n_tot, _signe_attendu(e, fam))


def c_booleen(nom, e, fam, jours):
    """Meme question, via un booleen jumeau au lieu d'un niveau."""
    ok_tot = n_tot = 0
    for _j, _dfe, brut in jours:
        if nom not in brut.columns or e["jumeau"] not in brut.columns:
            continue
        s = brut.dropna(subset=[nom, e["jumeau"]])
        ok_tot += int(((s[e["jumeau"]] > 0) == (s[nom] > 0)).sum())
        n_tot += len(s)
    return _verdict(ok_tot, n_tot, _signe_attendu(e, fam))


def c_niveau_implique(nom, e, fam, jours):
    """Le niveau reconstruit (`close + dist x tick`) est-il STABLE dans CHAQUE
    journee ? C'est tout ce qu'on peut exiger de ces colonnes : la mesure du
    14/09 a montre qu'elles ne designent PAS le meme niveau que leur jumeau
    homonyme (ecart jusqu'a 63 points). Le registre le dit en toutes lettres."""
    mauvais, vus = [], 0
    for j, _dfe, brut in jours:
        if nom not in brut.columns:
            continue
        s = brut.dropna(subset=["close", nom])
        if len(s) < N_MIN:
            continue
        vus += 1
        n = int((s["close"] + s[nom] * TICK).round(2).nunique())
        if n > 3:
            mauvais.append("%s:%d valeurs" % (j, n))
    if not vus:
        return None, "aucun jour exploitable"
    return not mauvais, "niveau instable sur %d/%d jours (%s)" % (
        len(mauvais), vus, ", ".join(mauvais[:4]))


def c_reconstruction(nom, e, fam, jours):
    """Le signe suit-il la pente de sa base, sur le decalage declare ?
    La pente est calculee DANS la journee : un `diff` a cheval sur deux seances
    compare deux marches differents."""
    base, k = e["base"], int(e["decalage"])
    ok_tot = n_tot = 0
    for _j, dfe, _brut in jours:
        if nom not in dfe.columns or base not in dfe.columns:
            continue
        d = dfe[base].astype(float).diff(k)
        s = dfe[nom].astype(float)
        m = d.notna() & s.notna() & (d != 0) & (s != 0)
        ok_tot += int(((d[m] > 0) == (s[m] > 0)).sum())
        n_tot += int(m.sum())
    return _verdict(ok_tot, n_tot, "direct")


def c_cumul(nom, e, fam, jours):
    """Le signe suit-il le cumul de sa base SUR LA SESSION ?
    Le cumul repart de zero chaque jour — cumuler a travers les journees
    rendait 54,8 % au lieu de 100 % le 14/09."""
    base = e["base"]
    ok_tot = n_tot = 0
    for _j, dfe, _brut in jours:
        if nom not in dfe.columns or base not in dfe.columns:
            continue
        cum = dfe[base].astype(float).cumsum()
        s = dfe[nom].astype(float)
        m = cum.notna() & s.notna() & (cum != 0) & (s != 0)
        ok_tot += int(((cum[m] > 0) == (s[m] > 0)).sum())
        n_tot += int(m.sum())
    return _verdict(ok_tot, n_tot, "direct")


def c_echelle(nom, e, fam, jours):
    """L'ordre de grandeur correspond-il a l'UNITE declaree ?

    Chaque ATR est confronte a SA propre echelle de barre : `atr_14m` au true
    range d'une minute, `atr_barre` a celui de quinze. Et on prend la MEDIANE
    DES RAPPORTS par jour : un jour ferie a un true range minuscule et
    fausserait un rapport calcule sur le tas."""
    rapports = []
    for _j, dfe, brut in jours:
        if nom not in dfe.columns:
            continue
        x = dfe[nom].astype(float).dropna()
        ref = ((brut["high"] - brut["low"]) if e["reference"] == "tr_1min"
               else (dfe["high"] - dfe["low"])).astype(float)
        med_ref = float(ref.median())
        if x.empty or not med_ref:
            continue
        facteur = TICK if e.get("unite") == "ticks" else 1.0
        rapports.append((float(x.median()) * facteur) / med_ref)
    if len(rapports) < 3:
        return None, "seulement %d jour(s) exploitables" % len(rapports)
    rapports.sort()
    r = rapports[len(rapports) // 2]
    lo, hi = e["plage"]
    return lo <= r <= hi, ("mediane des rapports x%.2f du TR %s sur %d jours "
                           "(plage %s-%s ; etendue %.2f-%.2f)"
                           % (r, e["reference"], len(rapports), lo, hi,
                              rapports[0], rapports[-1]))


def c_entre_niveaux(nom, e, fam, jours):
    """Un booleen « dedans » coincide-t-il avec les DEUX niveaux reconstruits ?

    Le controle le plus fort du registre, parce qu'il ne suppose rien : il
    confronte un booleen produit par le dumper aux niveaux que V3 reconstruit
    lui-meme depuis les distances. Mesure du 14/09 : 100,00 % sur 2940 barres
    par instrument. Il prouve au passage que la famille `dist_prev_*` est
    coherente avec elle-meme — ce qui n'allait pas de soi, ses colonnes de
    NIVEAU homonymes designant un autre niveau (cf `dist_prev_vah`)."""
    bas, haut = e["bornes"]
    ok_tot = n_tot = 0
    for _j, _dfe, brut in jours:
        besoin = {nom, bas, haut, "close"}
        if not besoin <= set(brut.columns):
            continue
        s = brut.dropna(subset=list(besoin))
        h = s["close"] + s[haut] * TICK
        b = s["close"] + s[bas] * TICK
        dedans = (s["close"] <= h) & (s["close"] >= b)
        ok_tot += int((dedans == (s[nom] > 0)).sum())
        n_tot += len(s)
    return _verdict(ok_tot, n_tot, "direct")


def c_valeurs(nom, e, fam, jours):
    """Les valeurs observees sont-elles incluses dans celles declarees ?"""
    declarees, extra, vus = set(e["valeurs"]), set(), 0
    for _j, dfe, brut in jours:
        src = dfe if nom in dfe.columns else brut
        if nom not in src.columns:
            continue
        vus += 1
        for v in pd.unique(src[nom].dropna()):
            v = bool(v) if isinstance(v, bool) else v
            if v not in declarees and not (
                    isinstance(v, (int, float)) and v in declarees):
                extra.add(v)
    if not vus:
        return None, "colonne absente de tous les jours"
    return not extra, "valeurs non declarees : %s (declarees %s)" % (
        sorted(map(str, extra)), e["valeurs"])


CONTROLES = {"jumeau": c_jumeau, "booleen": c_booleen,
             "niveau_implique": c_niveau_implique,
             "reconstruction": c_reconstruction, "cumul": c_cumul,
             "echelle": c_echelle, "entre_niveaux": c_entre_niveaux,
             "valeurs": c_valeurs}


def colonnes_lues_par_v3():
    """LE CLIQUET. Les accesseurs de COLONNE averes du depot :
    `val/_num/vrai/_texte(df, "X", i)` et les indices sur `df` / `dfe` / `brut`
    seulement. Un indice sur une variable quelconque serait une cle de
    dictionnaire, pas une colonne — les confondre rendait 107 noms au lieu de
    26 et noyait le controle."""
    out = {}
    for f in glob.glob("V3/**/*.py", recursive=True):
        base = os.path.basename(f)
        if base.startswith("test_"):
            continue
        try:
            arbre = ast.parse(open(f, encoding="utf-8").read())
        except (SyntaxError, UnicodeDecodeError):
            continue
        for n in ast.walk(arbre):
            c = None
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id in ("val", "_num", "vrai", "_texte")
                    and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant)
                    and isinstance(n.args[1].value, str)):
                c = n.args[1].value
            elif (isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name)
                  and n.value.id in ("df", "dfe", "brut")
                  and isinstance(n.slice, ast.Constant)
                  and isinstance(n.slice.value, str)):
                c = n.slice.value
            if c:
                out.setdefault(c, set()).add(base)
    return out
