"""Bot 5 VWAP-SD Mean Reversion (Sim3 emplacement, swap Bot 3 BN V4).

Edge : reversion VWAP daily SD bands (Bollinger-like) + confluence niveau institutionnel.
Source empirique : simulation 8j live_enriched (10-19/06) avec cooldown 5min.

4 setups (verdict empirique sur 8j) :
  A (NQ SHORT) : close ENTRE SD2u et SD3u + >=1 niveau resistance < 500 ticks au-dessus
                 ACTIVE - n=10 simules, PF 7.43, WR 80%
  B (NQ LONG)  : close ENTRE SD2d et SD3d
                 SHADOW - n=74 simules sans filtre, PF 0.52, edge INVERSE en live
  C (ES LONG)  : close ENTRE SD2d et SD3d ET vwap_slope_30 >= 0
                 SHADOW - n=35, PF 1.18 marginal (concentration 31/44 le 18/06)
  D (ES SHORT) : close ENTRE SD2u et SD3u
                 SHADOW - n=12 insuffisant statistiquement

Limits Mark Douglas : 5 trades / -$200 / +$150 par jour.
Sessions : RTH only US (13:30-20:00 UTC) avec 15min skip post-open.
Cooldown : 5 minutes apres entry/exit.
Filtre confluence Setup A : >=1 de {dist_mq_call, dist_prev_vah, dist_vwap_w_sd2u, dist_swing_high}
au-dessus du close dans 500 ticks (= 125 points NQ).

CAVEATS :
- Edge valide sur 8j live VIX > 30 (bear regime). Validation regime obligatoire
  quand VIX < 20 (peut s'inverser).
- n=10 Setup A = statistiquement modest, walk-forward DSR Lopez impossible.
  Critere live : reprendre evaluation apres 30j paper accumule.
- Setup B/C/D SHADOW : log_decision_jsonl collecte pour reevaluation 30j.
"""

__version__ = "1.0.0"
