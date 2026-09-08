# Mesure du lieu C2_DIV_DELTA — avant activation (08/09)

*Comptage de LIEUX et de signaux seulement — aucun devenir, aucun P&L lu
(brief §13 : « les distributions posent les seuils, jamais un devenir »).
Deux mesures indépendantes, même verdict : l'attendu N ≈ 20 du brief est
CONTREDIT avant le premier jour de journal.*

## 1. Mesure d'activation (Claude Code, lot avec chauffe ≥ 10 j)

| | jours évalués | lieux P10 | signaux (S/L) |
|---|---|---|---|
| ES | 52 | 6 | 3 + 2 = 5 |
| NQ | 52 | 7 | 4 + 1 = 5 |

Projection 60 jours : **~6 signaux par instrument** — N = 40 sur NQ
inatteignable ce cycle.

## 2. Décomposition (review code-reviewer, lot complet)

| | ES (77 j) | NQ (75 j) |
|---|---|---|
| Nouveaux extrêmes de session | 566 | 543 |
| ... dans le TROU DE CHAUFFE ATR (barres 0-5, p10 = NaN) | **326 (58 %)** | **315 (58 %)** |
| Lieux à P10 (barres ≥ 6) | 7 | 7 |
| Lieux à P15 / P20 (barres ≥ 6) | 13 / 19 | 11 / 16 |
| Extrêmes en chauffe qui SERAIENT lieu à P10 (proxy ATR médian du jour) | ~20 | ~20 |

## 3. Verdict

La cause première du N faible n'est PAS la largeur de P10 : **58 % des
nouveaux extrêmes tombent entre 9h30 et 11h00 ET, où `atr_barre` est NaN
(min_periods = 7) et où un lieu est impossible par construction** — or
c'est précisément la fenêtre où une session teste PDH/VAH. Élargir à
P15/P20 changerait la définition sans boucher le trou (13-19 lieux) ;
boucher le trou récupère ~20 lieux/instrument À P10 CONSTANT (≈ ×4).

La solution existe déjà dans le dépôt : **l'ATR de la VEILLE** (DECISIONS
07/09 — adopté par L1 pour exactement ce problème, disponible dès la
barre 0, sans fuite).

## 4. V2 mesurée (08/09, arbitrage Fable B appliqué — `atr_ref`)

Même comptage, seuil sur `atr_ref` (atr_barre, sinon ATR-veille) :

| | lieux v1 → v2 | signaux v1 → v2 |
|---|---|---|
| ES | 6 → **25** (×4,2) | 5 → **11** |
| NQ | 7 → **21** (×3,0) | 5 → **9** |

La prédiction de la review (« boucher le trou récupère ~20 lieux à P10
constant ») est TENUE. Projection 60 jours : ~11-13 signaux/instrument —
toujours sous N = 40 sur NQ seule (lecture probablement à 120 jours ou
ES+NQ à 1,3 test), mais le double de v1, et la fenêtre 9h30-11h00 existe
enfin. Adopté AVANT le premier rejeu officiel : aucune ligne v1 dans un
journal, pas de rétroactivité.

## 5. Décision

- Le setup reste **ACTIF tel quel** (v1 : P10 / atr_barre, date d'ombre
  20260908) — coût nul, le journal accumule, on n'active jamais
  rétroactivement.
- **Arbitrage Fable ouvert : ATR-veille pour le seuil de proximité** — pas
  P15/P20. Si adopté → v2 avec sa propre date d'ombre.
- Les lignes journalisées portent `niveau_prix`, `dist_niveau_ticks`,
  `cvd_prec` : la re-coupe du jour 61 se fait sans re-run.
