"""L5 — le risque : combien, et ou est le stop ?

L5 est la seule couche qui lit le SENS du trade. Elle ne cherche pas de setup :
elle refuse une position dont le stop n'a pas de place, dont la cible est mangee
par les frais, ou qui se prend dans un mur.

Mesure du 06/09 : L5 n'est PAS inerte — c'etait la mesure qui l'etait. Trois
vetos sur quatre se declenchent une fois l'ordre d'evaluation elimine.
"""

from __future__ import annotations

from V3.registre import porte

# Couts : SOURCE UNIQUE = hypothesis_runner (B1, audit Fable). Plus de copie —
# les memes nombres vivaient a trois endroits (chaine, vetos, runner).
from CORE.research.hypothesis_runner import COUT_DOLLARS, VAL_POINT   # noqa: E402


@porte("L5_VETO_GAMMA", "L5")
def _gamma(lec, etat, s):
    """Mur gamma, PAR SENS — forme minimale (A1, passe lecture 10/09).

    Bug A1 (audit Fable 09/09) : lisait `gamma_block_long` quel que soit le
    sens — un mur au-dessus bloquait des shorts sans raison. Maintenant : un
    LONG lit le mur du dessus ; un SHORT rend None (TROU_L5_VETO_GAMMA) parce
    que `gamma_block_short` N'EST PAS dans l'agregation 15 min — un trou
    honnete plutot qu'un veto inverse ; un sens inconnu rend None aussi.
    Porte OBSERVEE, et la garde YAML tient : la promouvoir en strict
    bloquerait TOUS les shorts par le trou. La passe complete (porter la
    colonne short dans l'agregation) reste au backlog."""
    side = lec["side"]
    if side is None or side < 0:
        return None
    return lec["gamma_block_long"]


@porte("L5_VETO_RVOL_EXTREME", "L5")
def _rvol(lec, etat, s):
    """Volume relatif aberrant : ce n'est plus le meme marche."""
    z = lec["rvol_zscore"]
    return z is not None and abs(z) >= s["zscore_max"]


@porte("L5_FRAIS_TROP_LOURDS", "L5")
def _frais(lec, etat, s):
    """La part des frais dans la distance au TP.

    REMPLACE le veto « SL < 2 x frais », qui n'etait pas inerte par accident
    mais PAR CONSTRUCTION : sur MNQ, un SL de 1,0 ATR-15m vaut ~40 $ contre
    5,64 $ de frais doubles — il faudrait que l'ATR-15m tombe sous 0,14 point.
    Ecrit pour du 1 minute en ticks fixes, transporte en 15 min ou il n'avait
    plus de sens.

    Ce qu'il voulait dire se mesure autrement, et cette version DIT quelque
    chose : MNQ 2,82 / (1,5 x 40 $) ~ 5 % ; MES 4,32 / (1,5 x 14 $) ~ 20 %. Un
    seuil a 10 % ne ferme rien sur MNQ et ferme tout sur MES — la meme
    conclusion que le cout par trade, atteinte par un autre chemin.
    """
    atr = lec["atr_ref"]                   # R3 : le meme metre que L3 et les brackets
    if atr is None or (isinstance(atr, float) and atr != atr) or atr <= 0:
        return None                        # A2 : ATR inconnu -> TROU, jamais False
    tp_usd = s["tp_atr"] * atr * VAL_POINT[lec["sym"]]   # C1 : fail-loud sym inconnu
    if tp_usd <= 0:
        return True
    return (COUT_DOLLARS[lec["sym"]] / tp_usd) > s["part_max"]
