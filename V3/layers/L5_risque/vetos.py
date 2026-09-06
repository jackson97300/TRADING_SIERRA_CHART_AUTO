"""L5 — le risque : combien, et ou est le stop ?

L5 est la seule couche qui lit le SENS du trade. Elle ne cherche pas de setup :
elle refuse une position dont le stop n'a pas de place, dont la cible est mangee
par les frais, ou qui se prend dans un mur.

Mesure du 06/09 : L5 n'est PAS inerte — c'etait la mesure qui l'etait. Trois
vetos sur quatre se declenchent une fois l'ordre d'evaluation elimine.
"""

from __future__ import annotations

from V3.registre import porte

# Couts et valeurs de point — micros MES / MNQ, commissions + 1 tick par cote.
COUT_DOLLARS = {"NQ": 2.82, "ES": 4.32}
VAL_POINT = {"NQ": 2.00, "ES": 5.00}


@porte("L5_VETO_GAMMA", "L5")
def _gamma(lec, etat, s):
    """Mur gamma dans le sens du TP. Devenir des rejetes -0,40 ATR sur ES."""
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
    atr = lec["atr_barre"]
    if not atr or atr <= 0:
        return False
    tp_usd = s["tp_atr"] * atr * VAL_POINT.get(lec["sym"], 5.0)
    if tp_usd <= 0:
        return True
    return (COUT_DOLLARS.get(lec["sym"], 4.32) / tp_usd) > s["part_max"]
