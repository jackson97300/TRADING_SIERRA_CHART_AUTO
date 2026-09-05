# INVENTAIRE DES SETUPS DEJA DEFINIS

Etabli le 05/09/2026, avant le choix des dix hypotheses de la mission phase 2.

**Ce document n'evalue rien.** Les chiffres sont recopies tels qu'ils sont
ecrits dans leur source, sans interpretation, sans conversion d'unite. Aucun
setup n'est propose : les dix, c'est Jackson qui les choisit ici.

**Regle de source** : une fiche sans `fichier:ligne` ou `document + section`
n'existe pas. Ce qui est deduit sans etre ecrit est marque `[infere]`.

---

## 0. Ce qui a ete cherche, et ou

| Emplacement cite dans la demande | Etat |
|---|---|
| `strategies/` | **n'existe pas** dans ce depot |
| `REVUE_DE_SESSION/` | **n'existe pas** |
| `backtests/` | **n'existe pas** |
| `LAUNCH/` | **n'existe pas** |
| `docs/TRADING_RULES.md` | **n'existe pas** |
| `docs/BACKTESTS_HISTORIQUE.md` | **n'existe pas** |
| `DECISIONS.md` | **n'existe pas** |
| `config/*.json` (battle_navale_v2, unified_thresholds…) | **n'existent pas** — `config/` ne contient que `families.yaml` et `applicabilite.yaml`, crees le 05/09 |
| `gamma_wall_rejection_strategy.py` | **introuvable** |
| `DOCS/` | 307 fichiers, exploite |
| `CORE/` | 1 490 fichiers, exploite |
| `bot4_v2/` | exploite |

Ces emplacements appartiennent au projet anterieur
`MIA-IA-SYSTEM-2026`, non present sur ce poste. **Cet inventaire ne couvre que
le depot courant.** L'ancien projet reste a inventorier separement, et il
contient probablement les regles de trading manuel.

---

## 1. LA BATTERIE V5 — 28 strategies testees, 41 resultats, AUCUN GO

**Source** : `DOCS/STRATEGY_BATTERY_V5_FULL_REPORT.md`, 27/04/2026.
**Donnees** : `ES/NQ_dataset_v5.parquet`, 24 mois, 351 000 barres.
**Triple barriere de ce test** : K_SL = 1,5 · K_TP = 2,0 · H = 60.
**Couts appliques** : ES 2,3 t · NQ 5,2 t.

> **Attention avant de reutiliser ces chiffres** : la triple barriere de ce test
> (SL 1,5 / TP 2,0 / H 60) n'est PAS celle de la mission phase 2 (TP 1,5 /
> SL 1,0 / H 20). Les donnees ne sont pas non plus les memes — `dataset_v5`
> est un lot Databento de 24 mois, la mission tourne sur 51 jours de
> `live_enriched`. Un setup NO-GO ici n'est pas mecaniquement NO-GO la-bas, et
> reciproquement. Ce qui se transpose, c'est **la liste des idees deja
> essayees**, pas leur verdict.

### Les 28 strategies, par code

| Code | Strategie | Meilleur PF | Sur | Verdict ecrit |
|---|---|---|---|---|
| JL2 | Long reversal pattern | 1,29 | ES (968 tr, WR 46,5 %) | NO-GO (PF<1.3) |
| H3 | Failed IB Poor High (Crabel) | 1,18 | NQ (764 tr, WR 39,8 %, EV +10,4 t) | NO-GO (PF<1.3) |
| JC2 | Color zone break | 1,11 | NQ (872 tr) | NO-GO (PF<1.3) |
| H4 | 1D Magnetism v5 (MenthorQ pinning) | 1,03 | NQ (1 565 tr) | NO-GO (PF<1.3) |
| JD | Divergence cluster | 1,02 | NQ (1 510 tr) | NO-GO (PF<1.3) |
| JL | Long bar continuation | 0,96 | NQ | NO-GO |
| H9 | VPIN regime v5 (Easley-Lopez) | 0,92 | NQ | NO-GO |
| JM | MenthorQ confluence 2+ niveaux | 0,91 | NQ | NO-GO |
| SE | VWAP + GEX regime v5 | 0,90 | ES (236 tr) | NO-GO |
| SB | GEX Flip Breakout v5 | 0,90 | NQ (451 tr) | NO-GO |
| JS | Volume spike | 0,89 | NQ | NO-GO |
| JC | Cluster at extreme (high/low) | 0,89 | ES | NO-GO |
| SH | Composite Rotation v5 (Dalton) | 0,87 | NQ | NO-GO |
| H1 | VWAP mean reversion (Dalton/Chan) | 0,85 | NQ | NO-GO |
| H8 | OFI residualise (Cont 2014) | 0,83 | NQ | NO-GO |
| JE | Edge zone fire | 0,80 | ES | NO-GO |
| H5 | Rejet VAH/VAL v5 (Dalton) | 0,80 | NQ | NO-GO |
| SF | IB Breakout + GEX v5 | 0,79 | ES (154 tr) | NO-GO |
| JT | Trapped traders cluster | 0,76 | NQ (414 tr) | NO-GO |
| JG | Game Changers dashboard composite | 0,73 | NQ (280 tr) | NO-GO |
| H2 | Open Drive continuation (Dalton) | 0,67 | NQ (56 tr) | NO-GO |

**Baseline ML v5 citee dans le meme rapport** : ES BUY PF 1,11 / ES SELL PF 0,63.

**Lecture** : aucune strategie n'atteint le seuil PF 1,3. La meilleure est un
« long reversal pattern » sur ES a 1,29 avec 968 trades. `H3 Failed IB Poor
High` est la seule a afficher une EV franchement positive (+10,4 t sur NQ) tout
en restant sous le seuil de PF.

---

## 2. SETUPS EN PRODUCTION — Bot 5 VWAP-SD

**Source** : `CORE/bot_vwap_sd/signal_engine.py`, `CORE/bot_vwap_sd/config.py`.
**Edge declare** (l.8-10) : *« mean reversion VWAP daily standard deviation
bands. Market makers short gamma fadent overbought (SD2u-SD3u) et oversold
(SD2d-SD3d). Microstructure documentee Dalton/Hurst. »*
**Unite de temps** : barre 1 min, evaluation stateless bar par bar.
**Ordre d'evaluation** : A, B, C, D — le premier qui declenche gagne.

### Setup A — NQ SHORT, zone SD2u–SD3u + confluence

- **Source** : `signal_engine.py:98-190`
- **Voit** : le prix entre dans la bande haute de la VWAP journaliere.
- **Declenche** : `symbol == NQ` ET `dist_vwap_d_sd2u < 0` (close au-dessus de
  SD2u) ET `dist_vwap_d_sd3u > 0` (close sous SD3u).
- **Confirme** : au moins un niveau de resistance au-dessus et proche, dans
  `SETUP_A_CONFLUENCE_THRESHOLD_TICKS`. Candidats : `dist_mq_call` (gamma
  wall), `dist_prev_vah`, `dist_vwap_w_sd2u`, `swing_high`.
- **Interdit** : `ib_range_atr >= SETUP_A_MAX_IB_RANGE_ATR` — *« IB > N ATR =
  volatility expansion = trend day en cours »*, motif de skip
  `TREND_DAY_IB_EXPANSION`.
- **Side** : SHORT.
- **TP / SL** : 80 t / 40 t (`config.py:61-62`).
- **Resultat ecrit** (l.99-100) : *« Empirique 8j : baseline PF 2.26 / avec
  confluence 500t PF 26.00 »*.
- **Statut** : **ACTIF** (`SETUP_A_ENABLED` par defaut `True`).

### Setup B — NQ LONG, zone SD2d–SD3d

- **Source** : `signal_engine.py:191-221`
- **Declenche** : `symbol == NQ` ET `dist_vwap_d_sd2d > 0` ET `dist_vwap_d_sd3d < 0`.
- **Side** : LONG. **TP / SL** : 40 t / 20 t.
- **Resultat ecrit** (l.192) : *« VERDICT EMPIRIQUE 20/06 : PF 0.52, EV -8.2t,
  -$304/8j -> EDGE INVERSE LIVE »*.
- **Statut** : **DESACTIVE**, mode SHADOW. Motif : `SHADOW_EDGE_INVERSE_LIVE`.

### Setup C — ES LONG, zone SD2d–SD3d ET pente >= 0

- **Source** : `signal_engine.py:223-254`
- **Declenche** : `symbol == ES` ET zone SD2d–SD3d ET `slope >= 0`.
- **Side** : LONG. **TP / SL** : 16 t / 8 t.
- **Resultat ecrit** (l.224-226) : *« PF 1.18, EV +1.0t, +$42/8j -> MARGINAL »*,
  avec le caveat *« concentration 31/44 le 18/06 (70 %) -> monitor si
  reactive »*.
- **Statut** : **DESACTIVE**, mode SHADOW.

### Setup D — ES SHORT, zone SD2u–SD3u

- **Source** : `signal_engine.py:256-285`
- **Declenche** : `symbol == ES` ET zone SD2u–SD3u.
- **Side** : SHORT. **TP / SL** : 12 t / 6 t.
- **Resultat ecrit** (l.258) : *« n=13 insuffisant statistiquement
  (market-analyst) »*. Motif de skip : `SHADOW_INSUFFICIENT_N`.
- **Statut** : **DESACTIVE**, mode SHADOW.

> **Note d'unite** : les TP/SL de ces quatre setups sont en **ticks fixes**, et
> different d'un facteur 6 entre A (80 t) et D (12 t). Aucune conversion n'est
> faite ici. La mission phase 2 travaille en ATR-5m : la transposition n'est pas
> mecanique.

---

## 3. SETUPS EN PRODUCTION — Bot Mean Revert VWAP

- **Source** : `CORE/bot_mean_revert/signal_engine.py`, 1 175 lignes.
- **Voit** (l.2-5) : *« Entry LONG : `dist_vwap_d_sdNd_pct <= -threshold` +
  filtres regime ES/NQ ; Entry SHORT : `dist_vwap_d_sdNu_pct >= threshold` +
  filtres regime ES/NQ »*.
- **SL / TP** : *« SL fixe ticks (20 ES / 35 NQ), TP = SL * RR (1.5) »*.
- **Reference** : `CORE/research/sweep_bot_mean_revert_v2.py`,
  `detect_mean_revert_signal`.
- **Filtre de qualite ajoute** (l.771) : *« Sample 37 trades : 12 kept, WR
  58.3 %, PF 2.62, PnL +$1637 (baseline -$679) »* — filtre sur `delta_bar` et
  `finish_strength` :
  - LONG : `delta_bar < DELTA_BAR_BEAR_LONG_MAX` (defaut −10) ET
    `finish_strength > FINISH_STRENGTH_LONG_MIN` (defaut 0)
  - SHORT : `delta_bar > DELTA_BAR_BULL_SHORT_MIN` (defaut +10) ET
    `finish_strength < FINISH_STRENGTH_SHORT_MAX` (defaut 0)
- **Garde-fou** (l.657) : `dist_vwap_d_pct`, apres un cas mesure a *« WR 26 %,
  PF 0.54 sur 23 trades juin »* (l.625).
- **Statut** : en production (Bot 1, Sim1).

---

## 4. SETUPS EN PRODUCTION — Bot 4 v2, scenarios

**Source** : `bot4_v2/decision/scenarios/`. Deux scenarios codes.

### Bearish_Rejection

- **Source** : `bot4_v2/decision/scenarios/bearish_rejection.py:1-18`
- **Statut ecrit** : *« KEEP + RECALIBRER (seul edge credible v1 PF 5.05) »*,
  *« le seul ayant survecu DSR test 14j (PF 5.05 sur N=55 trades premium, R:R
  median 2.0) »*. Recalibre apres 30 jours de shadow et une regression isotonique
  de P(win).
- **Methodologie declaree** : Wyckoff + Dalton confluence.
- **Declenche** : resistance majeure (`key_levels_resistance`, confluence >= 2
  dans 0,15 % du prix) ET rejection price action (`close < high` mais
  `close > previous_close`) ET order flow bearish (`delta_bar < 0` OU
  `bn_pressure_ask > bn_pressure_bid`).
- **Interdit** : regime de volatilite EXTREME (blacklist `vol_regime`).
- **Side** : SHORT seulement — *« asymetrie : LONG = Bullish_Continuation autre
  scenario »*.
- **Score heuristique** : `50 + 10 * (confluence_count − 1) + 10 (bearish OF)
  + 10 (regime trend down)`, max ~80.

### Sweep+Reclaim_N+1

- **Source** : `bot4_v2/decision/scenarios/sweep_reclaim_n1.py:1-24`
- **Origine** : audit ULTRATHINK 24/06, `trading-strategy-analyst`. ICT / Smart
  Money Concepts.
- **Declenche** : barre N — `sweep_high_this_bar = 1` OU `sweep_low_this_bar = 1` ;
  barre N+1 — reclaim : `close > bar_low(N)` si sweep_low, `close < bar_high(N)`
  si sweep_high.
- **Side** : LONG (sweep_low + reclaim) ou SHORT (sweep_high + reclaim).
- **Resultat ecrit** : *« edge naturel 50 % reclaim rate sur 14j data (vs 4 %
  RR>=1 v1 = TROUS) »*.
- **Critique du precedent, ecrite** : *« Failed Breakout v1 ne verifie pas N+1
  confirmation = mauvais Wyckoff »*.
- **Statut** : **DORMANT si les features de lag ne sont pas exposees** —
  *« Si JSONL sierra_enriched n'expose pas ces lag features, ce scenario reste
  DORMANT (heuristic_score=0) »*.

---

## 5. SETUP EN PRODUCTION — Bot 3 Breakout / Retest

- **Source** : `CORE/bot3_breakout_retest.py:1-20`
- **Canon declare** : Steidlmayer / Dalton.
- **Machine a etats** par `(symbol, level_name)` :
  1. `TOUCH` — orderflow crush detecte
  2. `PENDING_ACCEPTANCE` — attendre `BREAKOUT_N_ACCEPTANCE_BARS` (5) barres
  3. acceptance hybride TPO-printed : `close` du cote casse = 1,0 confirm ;
     `wick` du cote casse >= `BREAKOUT_WICK_ATR_RATIO * atr` = 0,5 confirm
  4. somme >= `BREAKOUT_ACCEPTANCE_CONFIRMS_THRESHOLD` (2,5) -> `ACCEPTED`,
     sinon `CANCELLED (CRUSH_ABSORBED)`
- **Origine des seuils** : *« FIX #10, market-analyst Section 2 »*.

---

## 6. DESIGNS ECRITS, NON RETROUVES EN PRODUCTION

| Document | Statut ecrit |
|---|---|
| `DOCS/BOT4_RANGE_FADE_CONFLUENCE_DESIGN.md` | *« DESIGN avant backtest. Code interdit avant verdict GO/NOGO Lopez. »* — 60+ sources de niveaux, detection en arriere-plan, confirmation a la barre suivante |
| `DOCS/SCENARIO_ENTRY_QUALITY_DESIGN.md` | a exploiter |
| `DOCS/BOT4_BN_V4_DESIGN.md` | a exploiter |
| `DOCS/IDEAS_BACKLOG_BN_V5_CAPITALIZED.md` | a exploiter |

---

## 7. SETUPS DONT LES COLONNES ONT CHANGE DE STATUT

Croisement avec `DOCS/features_provenance.csv` (05/09) et
`config/families.yaml`.

| Setup | Colonne utilisee | Statut aujourd'hui | Remplacante |
|---|---|---|---|
| VWAP-SD A | `dist_mq_call` | **B** (desaccord de seuil ES/NQ) | — |
| VWAP-SD A | `dist_prev_vah` | **B** — mais lire `prev_vah_lvl`, pas l'alias | §8 de CONVENTIONS |
| VWAP-SD A | `ib_range_atr` | **B** | — |
| VWAP-SD A–D | `dist_vwap_d_sd2u/sd3u/sd2d/sd3d` | **A** pour sd1u/sd2u/sd1d | — |
| Mean Revert | `dist_vwap_d_pct` | **A** | — |
| Mean Revert | `delta_bar`, `finish_strength` | **A** / **B** | — |
| Bearish_Rejection | `bn_pressure_ask/bid` | F18 Battle Navale | — |
| Sweep+Reclaim | `sweep_high_this_bar`, `sweep_low_this_bar` | **B**, F17 | — |
| Battery H1/H5 | `dist_cur_vah`, `dist_cur_val` | **A** | — |
| Battery H4/JM | `dist_mq_*` | **B** | — |
| Battery JG | `composite_poc_*` | **C** — source non alimentee, vide a 99 % | aucune |

---

## 8. CE QUI N'A PAS ETE TROUVE

- L'ancien projet `MIA-IA-SYSTEM-2026` n'est pas sur ce poste : ses
  `TRADING_RULES.md`, `BACKTESTS_HISTORIQUE.md`, `REVUE_DE_SESSION/` et les
  layers 1-4 de `launch_production_CLEAN_v2.py` restent a inventorier.
- Aucun fichier `gamma_wall_rejection_strategy.py`.
- Aucune trace ecrite de **trades pris a la main** avec leur raison, dans le
  depot courant. La demande citait cette liste comme premiers candidats : elle
  n'existe pas ici. Si elle existe, elle est dans les conversations ou dans
  l'ancien depot.
- `DOCS/SETUP_PERFORMANCE_REPORT.md` renvoie a
  `LOGS/setups_observed/*_setups_trades.jsonl` : ces journaux n'ont pas ete
  ouverts dans cet inventaire.

---

## 9. Pour choisir les dix

Trois observations, sans recommandation :

1. **Vingt-huit strategies ont deja ete testees et aucune n'a passe PF 1,3** —
   mais sur d'autres donnees et une autre triple barriere que la mission. Les
   reprendre telles quelles reviendrait a retester ; les ecarter sans le dire
   reviendrait a perdre l'information.
2. **Trois setups portent un resultat positif ecrit** : VWAP-SD A (PF 2,26
   baseline / 26,00 avec confluence, 8 jours), Bearish_Rejection (PF 5,05,
   N=55, 14 jours), Mean Revert avec filtre qualite (PF 2,62, 12 trades gardes
   sur 37). Les trois ont des effectifs faibles ou des periodes courtes.
3. **Deux setups sont documentes comme MORTS avec leur motif** : VWAP-SD B
   (edge inverse en live, PF 0,52) et VWAP-SD D (n=13 insuffisant). Les
   retester sans savoir pourquoi ils sont morts serait une repetition.
