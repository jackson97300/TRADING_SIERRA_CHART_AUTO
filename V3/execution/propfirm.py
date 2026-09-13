"""LES REGLES DE LA FIRME, modelisees — le mur que le bot ne doit jamais toucher.

    python -X utf8 V3/execution/propfirm.py        # l'etat des comptes

CE QUE CE MODULE SAIT, et que rien d'autre ne doit reimplementer : ou est le
plancher a cet instant, combien il reste de marge, si un retrait est possible,
et si le compte est mort. Les NOMBRES vivent dans `config/propfirm.yaml` : un
seuil en dur qu'on oublie a la prochaine evaluation est un compte perdu en
silence.

LES DEUX PHASES, et c'est la decouverte du 14/09 qui change la strategie.

  PHASE 1 — le plancher SUIT. Il monte avec les cloture gagnantes et ne
  redescend jamais. On part avec `dd_montant` de marge, et toute perte depuis
  le plus haut la mange. C'est la phase fragile : il faut gagner
  `dd_montant + verrou_marge` SANS jamais rendre `dd_montant` depuis le pic.

  PHASE 2 — le plancher est VERROUILLE a `taille + verrou_marge` et ne bouge
  plus jamais. A partir de la, on ne risque que ce qu'on a au-dessus, et chaque
  gain elargit definitivement le coussin. Le compte devient durable.

  Consequence operationnelle : l'objectif n'est PAS « gagner de l'argent »,
  c'est « atteindre le verrou ». Tant qu'il n'est pas atteint, la prudence vaut
  plus que le rendement ; apres, le calcul change. Un bot qui ne connait pas
  cette frontiere joue les deux phases de la meme facon, et se fait sortir dans
  la premiere.

MISE A JOUR ET APPLICATION SONT DEUX CHOSES DIFFERENTES. Le plancher peut ne se
recalculer qu'a la cloture (`dd_maj: eod`) tout en etant applique EN TEMPS
REEL : le toucher en seance tue le compte immediatement, meme si on se redresse
avant le soir. Les confondre fait croire qu'on a jusqu'au soir pour se
rattraper. On n'a pas.

AUCUN NOMBRE INVENTE. Un seuil absent du fichier vaut `None`, et le module
REFUSE de repondre plutot que de supposer — c'est la regle du depot, et elle
vaut double ici : supposer une perte journaliere maximale, c'est croire a un
garde-fou qui n'existe pas.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

RACINE = os.path.abspath(os.path.join(os.path.dirname(__file__), *[os.pardir] * 2))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

CHEMIN_REGLES = os.path.join(RACINE, "V3", "config", "propfirm.yaml")


class RegleAbsente(Exception):
    """Levee quand on interroge une regle que le fichier ne renseigne pas.

    Jamais de valeur par defaut : une limite supposee est pire qu'une limite
    absente, parce qu'on croit etre protege."""


def charger(chemin=None):
    import yaml
    p = chemin or CHEMIN_REGLES
    if not os.path.exists(p):
        raise FileNotFoundError("propfirm.yaml absent — les regles de la firme"
                                " ne se devinent pas : %s" % p)
    return yaml.safe_load(open(p, encoding="utf-8")) or {}


class Compte:
    """UN compte finance, et son plancher. Les montants sont des SOLDES, pas
    des gains : le plancher se compare a un solde."""

    def __init__(self, regles=None, numero=1, solde=None, pic_eod=None,
                 plancher=None, verrouille=False):
        self.r = regles or charger()
        c = self.r["compte"]
        self.taille = float(c["taille"])
        self.dd = float(c["dd_montant"])
        self.dd_maj = str(c["dd_maj"])
        self.verrou_marge = float(c["verrou_marge"])
        self.numero = int(numero)
        self.solde = float(self.taille if solde is None else solde)
        self.pic_eod = float(self.taille if pic_eod is None else pic_eod)
        self.verrouille = bool(verrouille)
        self.plancher = float(self.taille - self.dd if plancher is None else plancher)

    # --- le plancher ---------------------------------------------------------
    @property
    def plancher_verrou(self):
        """Le plancher DEFINITIF, une fois le verrou atteint."""
        return self.taille + self.verrou_marge

    @property
    def solde_de_verrou(self):
        """Le solde de cloture a partir duquel le plancher se fige. C'est LE
        chiffre a viser : au-dela, le compte change de nature."""
        return self.plancher_verrou + self.dd

    def _plancher_pour(self, pic):
        """Le plancher qu'un pic donne impose. Il ne descend JAMAIS et il ne
        depasse jamais le plancher de verrou."""
        candidat = min(pic - self.dd, self.plancher_verrou)
        return max(self.plancher, candidat)

    @property
    def marge(self):
        """Combien il reste avant la mort, au solde courant."""
        return self.solde - self.plancher

    @property
    def marge_jusqu_au_verrou(self):
        """Combien il reste a GAGNER pour sortir de la phase fragile."""
        return max(0.0, self.solde_de_verrou - self.pic_eod)

    @property
    def phase(self):
        return 2 if self.verrouille else 1

    # --- les evenements ------------------------------------------------------
    def mort(self, solde_instantane=None):
        """Le compte est-il perdu ? APPLIQUE EN TEMPS REEL : on compare le
        solde de l'INSTANT, pas celui de la cloture."""
        s = self.solde if solde_instantane is None else float(solde_instantane)
        return s <= self.plancher

    def apres_trade(self, solde_apres):
        """Un trade vient de se fermer. Rend True si le compte est mort.

        Le plancher ne bouge ici que si la politique le dit — `fin_de_trade` ou
        `intraday`. En `eod`, il attend la cloture."""
        self.solde = float(solde_apres)
        if self.dd_maj in ("fin_de_trade", "intraday") and not self.verrouille:
            self.pic_eod = max(self.pic_eod, self.solde)
            self.plancher = self._plancher_pour(self.pic_eod)
            self._verrouiller_si_besoin()
        return self.mort()

    def cloturer_journee(self, solde_eod=None):
        """Fin de seance : le pic et le plancher se mettent a jour, et le
        verrou se declenche si le solde de cloture l'atteint."""
        if solde_eod is not None:
            self.solde = float(solde_eod)
        if not self.verrouille:
            self.pic_eod = max(self.pic_eod, self.solde)
            self.plancher = self._plancher_pour(self.pic_eod)
            self._verrouiller_si_besoin()
        return self.plancher

    def _verrouiller_si_besoin(self):
        if not self.verrouille and self.plancher >= self.plancher_verrou:
            self.plancher = self.plancher_verrou
            self.verrouille = True

    def demander_retrait(self, montant):
        """Un retrait VERROUILLE le plancher immediatement si la firme le
        prevoit — c'est un arbitrage : on echange du potentiel de plancher
        contre de la securite, et on doit le savoir avant de cliquer."""
        if self.r["compte"].get("verrou_au_retrait") and not self.verrouille:
            self.plancher = max(self.plancher, self.plancher_verrou)
            self.verrouille = True
        self.solde -= float(montant)
        return self.mort()

    # --- les regles qui refusent de deviner ----------------------------------
    def perte_journaliere_max(self):
        """La limite du jour : la PLUS STRICTE entre celle de la firme et la
        notre.

        La notre est une PART de la marge restante, pas un montant fixe — donc
        elle se resserre seule quand le compte va mal. Consequence : une suite
        de journees perdantes ne peut jamais tuer le compte, elle ne fait que
        le retrecir. Seule une secousse intra-journaliere le peut, et aucune
        limite journaliere ne protege de ca — c'est le stop par trade qui s'en
        charge.

        Si la firme n'a pas ete verifiee, on rend la notre : avoir une limite
        a soi vaut mieux que n'en avoir aucune en attendant de lire un site."""
        firme = self.r["compte"].get("perte_journaliere_max")
        pct = self.r["compte"].get("perte_journaliere_pct_marge")
        candidats = []
        if firme is not None:
            candidats.append(float(firme))
        if pct is not None:
            candidats.append(float(pct) * self.marge)
        if not candidats:
            raise RegleAbsente(
                "aucune limite journaliere : ni celle de la firme (a lire sur"
                " son site) ni la notre (`perte_journaliere_pct_marge`)."
                " Croire a un garde-fou absent est pire que savoir qu'il manque.")
        return min(candidats)

    def consistance_max(self, rang_retrait):
        """La part maximale qu'une seule journee a le droit de peser dans le
        gain total, au rang de retrait donne (1 = premier retrait)."""
        table = self.r["retrait"]["consistance_par_rang"]
        return float(table[min(max(rang_retrait, 1), len(table)) - 1])

    def retrait_possible(self, gain_total, meilleur_jour, rang_retrait=1):
        """(possible, motif). Deux conditions : l'objectif, et la consistance."""
        objectif = self.r["retrait"].get("objectif")
        if objectif is None:
            raise RegleAbsente("objectif de retrait non renseigne dans propfirm.yaml")
        if gain_total < float(objectif):
            return False, "objectif non atteint (%.2f / %.2f)" % (gain_total, objectif)
        part = self.consistance_max(rang_retrait)
        if gain_total > 0 and meilleur_jour / gain_total > part:
            return False, ("consistance : la meilleure journee pese %.0f %% du gain,"
                           " maximum %.0f %%" % (100 * meilleur_jour / gain_total,
                                                 100 * part))
        return True, "objectif et consistance satisfaits"

    def resume(self):
        return ("compte #%d — solde %.2f | plancher %.2f | marge %.2f | phase %d%s"
                % (self.numero, self.solde, self.plancher, self.marge, self.phase,
                   "" if self.verrouille
                   else " | reste %.2f a gagner pour verrouiller"
                        % self.marge_jusqu_au_verrou))


# --- le suivi des comptes : combien perdus, combien retires -----------------
def chemin_etat(regles=None):
    r = regles or charger()
    return os.path.join(RACINE, r["suivi"]["chemin_etat"])


def lire_suivi(regles=None):
    p = chemin_etat(regles)
    if not os.path.exists(p):
        return {"comptes": [], "retraits": []}
    return json.load(open(p, encoding="utf-8"))


def ecrire_suivi(etat, regles=None):
    """Ecriture atomique — la convention du depot, apprise a ses depens."""
    p = chemin_etat(regles)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = "%s.%d.tmp" % (p, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(etat, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _horodatage():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ouvrir_compte(regles=None):
    """Numerote a partir de `premier_numero`, et n'oublie jamais les perdus."""
    r = regles or charger()
    e = lire_suivi(r)
    numero = (max([c["numero"] for c in e["comptes"]], default=
                  int(r["suivi"]["premier_numero"]) - 1) + 1)
    e["comptes"].append({"numero": numero, "ouvert_le": _horodatage(),
                         "etat": "actif", "perdu_le": None, "motif": None})
    ecrire_suivi(e, r)
    return numero


def perdre_compte(numero, motif, regles=None):
    e = lire_suivi(regles)
    for c in e["comptes"]:
        if c["numero"] == numero:
            c.update(etat="perdu", perdu_le=_horodatage(), motif=str(motif))
    ecrire_suivi(e, regles)


def noter_retrait(numero, montant, regles=None):
    e = lire_suivi(regles)
    e["retraits"].append({"numero": numero, "quand": _horodatage(),
                          "montant": float(montant)})
    ecrire_suivi(e, regles)


def main():
    r = charger()
    e = lire_suivi(r)
    perdus = [c for c in e["comptes"] if c["etat"] == "perdu"]
    total = sum(x["montant"] for x in e["retraits"])
    c = Compte(r, numero=max([x["numero"] for x in e["comptes"]], default=1))
    print("REGLES — verifiees le %s" % r.get("verifie_le", "?"))
    print("  compte %.0f, drawdown %.0f, mise a jour %s, applique en temps reel : %s"
          % (c.taille, c.dd, c.dd_maj, r["compte"]["dd_applique_en_temps_reel"]))
    print("  verrou du plancher a %.0f, atteint quand la cloture touche %.0f"
          % (c.plancher_verrou, c.solde_de_verrou))
    print("\nSUIVI")
    print("  comptes ouverts : %d | perdus : %d" % (len(e["comptes"]), len(perdus)))
    for x in perdus:
        print("     #%d perdu le %s — %s" % (x["numero"], x["perdu_le"], x["motif"]))
    print("  retraits : %d, total %.2f" % (len(e["retraits"]), total))
    print("\n" + c.resume())
    return 0


if __name__ == "__main__":
    sys.exit(main())
