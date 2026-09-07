# Mesure C2_EOD — distribution de |rendement_r| (pose r_min)

*Attendu écrit avant : p25 ≈ 0,2-0,3 ; p50 ≈ 0,4 ; r_min = p25
par instrument. Normalisation par le range cash à 15h30 (OHLC,
provenance A) — écart au « ATR-jour » du brief documenté dans
la docstring de `mesure_c2.py` et flaggé dans DECISIONS.md.
Aucun devenir lu.*

## ES — 56 journées mesurées (écartées : {'jour_vide': 15, 'barre_eod_absente': 6})
- |rendement_r| : p10 0.175 | **p25 0.273** | p50 0.459 | p75 0.611 | p90 0.727
- **r_min retenu (p25, pré-déclaré) : 0.273** — garde 42/56 jours
- attendu tenu ? p25 dans [0,2 ; 0,3] : OUI ; p50 ≈ 0,4 : OUI

## NQ — 56 journées mesurées (écartées : {'jour_vide': 13, 'barre_eod_absente': 6})
- |rendement_r| : p10 0.151 | **p25 0.275** | p50 0.478 | p75 0.649 | p90 0.767
- **r_min retenu (p25, pré-déclaré) : 0.275** — garde 42/56 jours
- attendu tenu ? p25 dans [0,2 ; 0,3] : OUI ; p50 ≈ 0,4 : OUI
