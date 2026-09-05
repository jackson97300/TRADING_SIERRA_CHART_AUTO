# INVENTAIRE DES SETUPS — les deux depots, fusionne

Etabli le 05-06/09/2026, avant le choix des dix hypotheses de la mission phase 2.
Fusion de deux lectures independantes : Fable a lu `MIA-IA-SYSTEM-2026-` et
l'instantane GitHub du depot courant ; Claude Code a lu le depot local courant.

**Ce document n'evalue rien.** Les chiffres sont recopies tels qu'ecrits, avec
leur periode et leur effectif, sans conversion d'unite.
**Regle de source** : pas de `fichier:ligne` ou `document + section`, pas de
fiche. `[stated]` = ecrit tel quel ; `[infere]` = deduit, a confirmer.

---

## 0. LE CADRE — ce que Jackson a ecrit lui-meme

`DOCS/MIA_NOUVEAU_PARADIGME.md`, 01/03/2026 :

> « Je sais quel type de journee c'est, j'attends le prix sur mes niveaux, je
> confirme avec l'order flow. » … « On ne CHERCHE plus de trades. On ATTEND que
> le marche vienne a nous. »

Trois niveaux : **REGIME** (calcule une fois a 10h30 — `open_type`, `open_zone`,
`ib_range_atr`, `profile_shape`, `vix_regime`) → **ZONE** (6-8 niveaux max, profil
de volume + MenthorQ en confluence) → **TRIGGER** (Battle Navale + CVD, adapte
au regime). Cinq regimes : TREND, ROTATION, REVERSAL, BREAKOUT, INCERTAIN.

C'est mot pour mot L2 → L3 → L4 de l'architecture actuelle. **Les dix
hypotheses gagnent a s'ecrire par regime** — c'est la seule structure qui vienne
de Jackson et qui ait survecu a toutes les versions.

---

## 1. LE CROISEMENT — cinq setups proposes ont deja ete testes

C'est l'apport principal de la fusion, et il change la lecture de la proposition
finale de Fable.

**Source des verdicts** : `DOCS/STRATEGY_BATTERY_V5_FULL_REPORT.md`, 27/04/2026,
`ES/NQ_dataset_v5.parquet`, 24 mois, 351 000 barres, triple barriere
K_SL 1,5 / K_TP 2,0 / H 60, couts ES 2,3 t · NQ 5,2 t.

| Setup propose | Code deja teste | PF NQ | PF ES | Verdict ecrit |
|---|---|---|---|---|
| **S3** extremes de la VA courante | **H5** Rejet VAH/VAL (Dalton) | 0,80 | 0,66 | NO-GO |
| **S8** retour VWAP en tendance | **H1** VWAP mean reversion (Dalton/Chan) | 0,85 | 0,68 | NO-GO |
| **S6** cassure IB + pullback | **SF** IB Breakout + GEX | 0,70 | 0,79 | NO-GO |
| **S10** rebond niveaux veille | **JM** MenthorQ confluence 2+ | 0,91 | 0,64 | NO-GO |
| **S1** rejet de mur gamma | **H4** 1D Magnetism (MenthorQ pinning) | 1,03 | 0,84 | NO-GO |
| S7 ouverture / regle 80 % | **H2** Open Drive continuation | 0,67 (56 tr) | 0,58 (59 tr) | NO-GO |
| S5 double top | **JT** Trapped traders cluster | 0,76 | 0,70 | NO-GO |
| S4 exhaustion | **JL2** Long reversal pattern | 0,91 | **1,29** | NO-GO (PF<1,3) |
| S9 sweep + reprise | *aucun equivalent teste* | — | — | — |
| S2 absorption RVOL | *aucun equivalent teste* | — | — | — |

> **Ce que ce tableau dit, et ce qu'il ne dit pas.** La triple barriere de ce
> test (SL 1,5 / TP 2,0 / H 60) n'est PAS celle de la mission (TP 1,5 / SL 1,0 /
> H 20), et les donnees non plus — 24 mois de Databento contre 51 jours de
> `live_enriched`. **Un NO-GO la-bas n'est pas un NO-GO ici.** Ce qui se
> transpose, c'est que ces idees ont deja ete essayees a grande echelle et n'ont
> pas passe PF 1,3. Les reprendre est legitime ; les reprendre sans le savoir ne
> l'est pas.

**Les deux seuls setups sans equivalent teste sont S2 (absorption RVOL) et S9
(sweep + reprise).** Ce sont, a ce titre, les plus neufs de la liste.

---

## 2. STATUTS DE COLONNES — six corrections apres verification

Verifie contre `DOCS/features_provenance.csv` et `config/families.yaml` du 05/09.

| Colonne | Annonce dans la v0 | **Mesure** | Consequence |
|---|---|---|---|
| `va_position_pct` | B, F10 | **C** — nulls 53 %/jour | **S3 n'est pas ecrivable en l'etat** |
| `range_pos` | A/B, F10 | **C** | S2 perd un de ses confirmateurs |
| `rvol_absorb_buy/sell` | B, F14 | **R** — actif 1,0 % et 0,9 % | S2 est un evenement rare : N sera faible |
| `dist_asia_high` | B | **n'existe pas** | seule `dist_asia_high_pct` existe, et elle est en C (signe inverse) |
| `dist_mq_call_0dte` | C, 56 % nulls | **B**, hors noyau | utilisable, mais absente du noyau commun |
| `bn_absorb_ask` | « morte en live » | **B**, F14 | reclassee apres le crible corrige |

**Substituts disponibles pour S3** : `inside_cur_va` (**A**, dans le noyau),
`dist_cur_vah` / `dist_cur_val` (**A**). La position relative dans la VA doit
etre reconstruite depuis ces trois-la, pas lue depuis `va_position_pct`.

---

## 3. FICHES — depot ancien (lecture Fable)

### S1 — Rejet de mur gamma (Call / Put Wall)
- **Source** : `MIA-IA-SYSTEM-2026-/strategies/gamma_wall_rejection_strategy.py` ; `rule_engine.py` R6/R7 ; `MIA_SIM_REPORT` (trades `MQ_CALL0D`).
- **Voit** [stated] : le prix arrive a moins de N ticks d'un Call Wall (short) / Put Wall (long).
- **Declenche** [stated] : bougie de rejet, meche >= seuil, `volume_spike` 1,3-1,5x. R6 : `dist_mq_call_0dte` < 15 ticks, poids 0,20 si < 8.
- **Confirme** [stated] : delta contraire, BN edge zone. **Interdit** [infere] : en TREND contre la tendance.
- **Mesure** : SIM janvier 2W-0L le 26/01 (off-hours, ±12 t) ; bench 04/09 « 100 % » sur NQ avec 13-57 touches — **suspect de niveau mobile**, 40-60 % sur ES. Aucune mesure sur >= 5 jours.
- **Noyau v2** : `dist_mq_call` / `dist_mq_put` (B, F11, dans le noyau), `ask_pct` / `bid_pct` (A), `bar_upper/lower_wick_pct` (A), `rvol_r` (A recalculee).

### S2 — Absorption RVOL (entree autonome)
- **Source** : `CORE/mia_entry.py` couche 3B (13/03/2026) ; `CORE/rvol.py`.
- **Voit** [stated] : « L'absorption est le signal le plus puissant en range trading » — `rvol >= 2,0x` + delta contradictoire + finish contradictoire.
- **Declenche** [stated] : `rvol_absorb_buy == 1` → LONG ; `rvol_absorb_sell == 1` → SHORT.
- **Mesure** : `MIA_SIM_REPORT` 13/03 — 20 trades sur **1 jour**, WR 50 %, PF 1,79, +230 $, tous SHORT (journee baissiere).
- **Noyau v2** : declencheurs en **R** (rares, ~1 %) — mis a part pour la phase 2. Confirmateurs : `inside_cur_va` (A), `bn_score_raw` (B) ; `range_pos` est **C**.
- **Sans equivalent dans la batterie V5.**

### S3 — Mean reversion aux extremes de la VA courante
- **Source** : `mia_entry.py` couche 3C ; `rule_engine.py` R11.
- **Mesure** [stated] : bench 13/03 — VA TOP (> 80 %) 58 % WR short **avg −1,9 pts** ; VA BOT (< 20 %) 59 % WR long avg +1,8 pts. **Un jour. Le short a un WR positif et une esperance negative.**
- **Interdit** [stated, `lessons.md`] : « VA basse en trend baissier n'est pas un BUY, c'est un breakdown » ; R11 exige `vwap_slope >= −0,1`.
- **Bloquant** : `va_position_pct` est **C**. A reecrire sur `inside_cur_va` + `dist_cur_vah/val`.
- **Deja teste** : H5, PF 0,80 / 0,66.

### S4 — Exhaustion multi-barres
- **Source** : `mia_entry.py` couches 3E/3F.
- **Declenche** [stated] : 3+ barres consecutives meme direction + finish contradictoire (>= 15, fort >= 25) ; deceleration (`momentum_5b` > ±4 + finish contradictoire) ; climax (`rvol >= 2,5x`) ; delta exhaustion.
- **Mesure** [stated] : « NQ 13/03 : 3down + finish > 20 = 75 % WR, avg +3,1 pts » ; deceleration « 71 % WR ». **Un jour.**
- **ALERTE UNITE** : `momentum_5b` etait un **lag 2**, mesure a 100 % cette semaine. Le seuil ±4 a ete cale sur une colonne fausse. Recalibrage = hypothese du cycle suivant, **pas avant le tag**.
- **Noyau v2** : `finish_strength` (B), `finish_delta_pct` (A), `momentum_5b_r` (A recalculee), `ctx_delta_exhaustion` / `ctx_climax_signal` (B, F14, dans le noyau).

### S5 — Double top / bottom avec divergence delta (booster)
- **Source** : `CORE/mia_double_top.py` — « Option B : confirmation/booster, pas un regime » ; R13/R14.
- **Mesure** : R13 « NQ 65 % WR » (3 jours) ; bench 04/09 : double top actif **47 % des barres sur ES** (seuil en ticks trop large), WR ~51/45 %.
- **Noyau v2** : `ctx_double_top_trap` (B, F21, dans le noyau), `delta_div_*` (B, F15).

### S6 — Cassure de l'IB + pullback (regime BREAKOUT)
- **Source** : paradigme §Regime 4 ; `MIA-IA-SYSTEM-2026-/strategies/initial_balance_breakout.py`.
- **Declenche** [stated] : `ib_range_atr < 0,40` OU `profile_shape = B` → attendre cassure IB High/Low + pullback ; volume eleve (`vol_per_sec`), delta fort dans le sens, pas d'absorption contra. SL de l'autre cote de l'IB, TP = 1,5x IB.
- **Mesure** : un seul trade trouve (`MIA_SIM_REPORT` #14, ES, SL). Non mesure.
- **Noyau v2** : `ib_broken_up` (B, F5, dans le noyau), `ib_range_atr` (B), `dist_ib_high/low` (A), `vol_per_sec` (A).
- **Deja teste** : SF, PF 0,79 / 0,70. Voisin : **H3 Failed IB Poor High, PF 1,18 NQ, EV +10,4 t** — le meilleur EV de toute la batterie.

### S7 — Ouverture hors VA veille, echec de retour, regle des 80 %
- **Source** : `CORE/game_changers.py` (`classify_open_type`, `Rule80Pct`) ; paradigme TREND / REVERSAL.
- **Voit** [stated] : 12 types d'ouverture, 7 zones vs VA veille ; « OAOR qui echoue et revient dans la VA → regle 80 % » ; « si un OD echoue (ODF) → basculer en REVERSAL ».
- **Mesure** : aucune trouvee. Parite C++/Python verifiee (105/105).
- **Noyau v2** : `open_type` (B, F4, noyau), `rule_80pct` (B, F4, noyau), `open_relation_type` (B, F3, noyau), `ctx_failed_auction` (B, F21, noyau), `dist_prev_vah/val` (A via `_lvl`).

### S8 — Retour VWAP en tendance
- **Source** : paradigme §Trigger TREND ; `rule_engine.py` R10, R2.
- **Declenche** [stated] : `vwap_slope > 0,5` ET `price_diff < −2` → BUY (poids 0,12).
- **Mesure** [stated] : « ES 62 % WR, n = 360, p = 0,001 » sur **3 jours** (30/03-01/04). `lessons.md` : « 3 jours = insuffisant ».
- **Noyau v2** : `dist_vwap_rth_r` (A recalculee), `vwap_slope_10` (B, F10, noyau), `cvd_sess_r` / `cvd_rth_r` (A recalculees).
- **Deja teste** : H1, PF 0,85 / 0,68.

### S9 — Sweep de liquidite + reprise (Judas, AMD)
- **Source** : `CORE/mia_amd.py` ; `strategies/liquidity_sweep_reversal.py`.
- **Declenche** [stated] : sweep = depassement du high/low Asie de SWEEP_MIN ticks (**NQ 15, ES 4**) ; Judas = sweep puis retour dans le range (NQ 10 / ES 3).
- **Mesure** : aucune sur trades. Bench 04/09 : « AMD Power of 3 jamais porte » cote enricher.
- **Noyau v2** : `sweep_high/low_this_bar` (B, F17, noyau), `judas_swing_active` (B, F2), `dist_ovn_high/low` (A, F12). **`dist_asia_*` : la colonne brute n'existe pas ; `dist_asia_high_pct` est en C (signe inverse).**
- **Sans equivalent dans la batterie V5.** Le depot courant en a une version codee : **Sweep+Reclaim_N+1** (§4).

### S10 — Rebond / rejet sur les niveaux de la veille
- **Source** : `rule_engine.py` R1-R5b (< 12 ticks, poids 0,25 si < 5) ; `strategies/pvwap_magnetic_bounce.py`.
- **Mesure** : bench 04/09 — « PVAL dessous + BULL div 78,6 % N = 70 ES » ; « PVAL dessus + BEAR div 63,4 % N = 142, **avg −1,48 ticks** » (WR positif, esperance negative). Seuils en ticks ES appliques au NQ.
- **Noyau v2** : `dist_prev_vpoc/vah/val` (A, via `_lvl`), `dist_prev_vwap_rth_r` (A recalculee, **represente 39 colonnes sur NQ**), `delta_div_*` (B).
- **Deja teste** : JM, PF 0,91 / 0,64.

### S11 — Battle Navale (score composite)
- **Source** : `config/battle_navale_v2.json` ; `mia_entry.py`.
- **Voit** [stated] : score sur 6 facteurs (price action 0,20, orderflow 0,25, volume profile 0,15, MenthorQ 0,20, VIX 0,10, DOM 0,10), seuils ±0,7.
- **Mesure** : `MIA_SIM_REPORT` 13/03 — les 20 trades portent tous `EDGE_SELL+COLOR2_DN` : **BN etait la confirmation de chaque trade, pas le declencheur**.
- **Statut** : confirmation en production ; comme declencheur, **abandonne** (BN V5, PATTERN_11).
- **Noyau v2** : `bn_score_raw` (B, F18), `bn_absorb_ask` (B — reclassee), `bn_color_up_2` (B).

### S12 — Fade des extremes en ROTATION
- **Source** : paradigme §Regime 2 — « OAIR ET `ib_range_atr` entre 0,40 et 0,80 ET `profile_shape = D` → fader les extremes VA/IB, TP = VPOC session ou PVPOC ».
- **Statut** : decrit, pas code comme unite. S2 + S3 en sont les triggers.
- **Deja teste, voisin** : SH Composite Rotation (Dalton), PF 0,87 / 0,79.

### S13 — Douze setups MenthorQ « avances », non mesures
`blind_spot_magnetic_pull`, `call_put_channel_rotation`, `cvd_divergence_trap`,
`dealer_flip_breakout`, `gamma_pin_reversion`, `gamma_wall_break_and_go`,
`hvl_magnet_fade`, `iceberg_tracker_follow`, `next_wall_micro_zone_scalp`,
`profile_gap_fill`, `stacked_imbalance_continuation`, `es_nq_lead_lag_mirror`.
**Aucune mesure.** Le `BACKTESTS_HISTORIQUE` global du systeme de decembre donne
134 trades, WR 21,6 %, −2 875 $. A traiter comme liste d'idees.

### S14 — Regles issues de 3 jours (`rule_engine.py`, 02/04/2026)
R12 `new_swing_high` → BUY (« NQ 64 % WR, p = 0,036 ») ; R15 « VIX Call 0DTE
au-dessus → BUY (ES 66 %, n = 547) » ; R16 VIX Put → SELL ; R9 composite VPOC.
**Abandonnees** avec le RuleEngine. `lessons.md` : « 3 jours = insuffisant »,
« 90-100 % WR sur 15 trades = pas significatif ».

---

## 4. FICHES — depot courant (lecture Claude Code)

### C1 — Bot 5 VWAP-SD, setups A a D
**Source** : `CORE/bot_vwap_sd/signal_engine.py`, `config.py`. Barre 1 min,
evaluation stateless, ordre A → B → C → D, premier qui declenche gagne.
**Edge declare** (l.8-10) : *« mean reversion VWAP daily standard deviation
bands. Market makers short gamma fadent overbought (SD2u-SD3u) et oversold
(SD2d-SD3d). Microstructure documentee Dalton/Hurst. »*

| | Declencheur | Side | TP/SL | Mesure ecrite | Statut |
|---|---|---|---|---|---|
| **A** | NQ, `dist_vwap_d_sd2u < 0` ET `sd3u > 0`, + confluence >= 1 resistance proche (`dist_mq_call`, `dist_prev_vah`, `dist_vwap_w_sd2u`, `swing_high`) | SHORT | 80 t / 40 t | *« Empirique 8j : baseline PF 2.26 / avec confluence 500t PF 26.00 »* | **ACTIF** |
| **B** | NQ, `sd2d > 0` ET `sd3d < 0` | LONG | 40 t / 20 t | *« PF 0.52, EV −8.2t, −$304/8j → EDGE INVERSE LIVE »* | DESACTIVE, shadow |
| **C** | ES, zone SD2d-SD3d ET `slope >= 0` | LONG | 16 t / 8 t | *« PF 1.18, EV +1.0t, +$42/8j → MARGINAL »*, caveat *« concentration 31/44 le 18/06 (70 %) »* | DESACTIVE, shadow |
| **D** | ES, zone SD2u-SD3u | SHORT | 12 t / 6 t | *« n=13 insuffisant statistiquement »* | DESACTIVE, shadow |

Filtre anti-trend sur A : `ib_range_atr >= SETUP_A_MAX_IB_RANGE_ATR` → skip
`TREND_DAY_IB_EXPANSION`, *« IB > N ATR = volatility expansion = trend day »*.

> **Note d'unite** : les TP/SL vont de 80 t (A) a 12 t (D), un facteur 6. La
> mission travaille en ATR-5m : la transposition n'est pas mecanique.

### C2 — Bot Mean Revert VWAP
**Source** : `CORE/bot_mean_revert/signal_engine.py`, 1 175 lignes. En production (Bot 1, Sim1).
- **Declenche** [stated l.2-5] : LONG `dist_vwap_d_sdNd_pct <= −seuil` ; SHORT `dist_vwap_d_sdNu_pct >= seuil`, + filtres de regime ES/NQ.
- **SL / TP** : SL fixe 20 t ES / 35 t NQ, TP = SL × 1,5.
- **Filtre de qualite** (l.771) : *« Sample 37 trades : 12 kept, WR 58.3 %, PF 2.62, PnL +$1637 (baseline −$679) »* — LONG si `delta_bar < −10` ET `finish_strength > 0` ; SHORT en miroir.
- **Garde-fou** (l.657) apres un cas a *« WR 26 %, PF 0.54 sur 23 trades juin »*.

### C3 — Bot 4 v2, Bearish_Rejection
**Source** : `bot4_v2/decision/scenarios/bearish_rejection.py:1-18`.
- **Statut ecrit** : *« KEEP + RECALIBRER (seul edge credible v1 PF 5.05) »*, *« le seul ayant survecu DSR test 14j (PF 5.05 sur N=55 trades premium, R:R median 2.0) »*.
- **Declenche** : resistance majeure (confluence >= 2 dans 0,15 % du prix) ET `close < high` mais `close > previous_close` ET (`delta_bar < 0` OU `bn_pressure_ask > bn_pressure_bid`).
- **Interdit** : regime de volatilite EXTREME. **Side** : SHORT seulement.
- **Score** : `50 + 10 × (confluence − 1) + 10 (OF bearish) + 10 (trend down)`.

### C4 — Bot 4 v2, Sweep+Reclaim_N+1
**Source** : `bot4_v2/decision/scenarios/sweep_reclaim_n1.py:1-24`. ICT / Smart Money Concepts.
- **Declenche** : barre N `sweep_high_this_bar = 1` OU `sweep_low_this_bar = 1` ; barre N+1 reclaim (`close > bar_low(N)` si sweep_low, miroir sinon).
- **Mesure ecrite** : *« edge naturel 50 % reclaim rate sur 14j data (vs 4 % RR>=1 v1 = TROUS) »*.
- **Critique du precedent** : *« Failed Breakout v1 ne verifie pas N+1 confirmation = mauvais Wyckoff »*.
- **Statut** : **DORMANT si les features de lag ne sont pas exposees**.
- **C'est la version codee de S9.**

### C5 — Bot 3, Breakout / Retest
**Source** : `CORE/bot3_breakout_retest.py:1-20`. Canon Steidlmayer / Dalton.
Machine a etats : `TOUCH` (orderflow crush) → `PENDING_ACCEPTANCE` (5 barres) →
acceptance hybride TPO-printed (`close` du cote casse = 1,0 ; `wick >=
BREAKOUT_WICK_ATR_RATIO × atr` = 0,5) → somme >= 2,5 = `ACCEPTED`, sinon
`CANCELLED (CRUSH_ABSORBED)`.
**C'est la version codee de S6.**

---

## 5. CE QUI A ETE TRADE — et ce qui a seulement ete ecrit

| Setup | Trade | Support |
|---|---|---|
| S1 rejet de mur gamma | SIM janvier (off-hours) | logs 26/01 |
| S2 absorption RVOL | SIM 13/03 | `MIA_SIM_REPORT` |
| S3 range entry VA | SIM 13/03 | `MIA_SIM_REPORT` |
| S11 BN comme confirmation | SIM 13/03 | `MIA_SIM_REPORT` |
| C1 VWAP-SD A | **paper / live 8 jours** | mesure dans le code |
| C2 Mean Revert | **production Sim1** | mesure dans le code |
| C3 Bearish_Rejection | **14 j DSR + 30 j shadow** | docstring |
| S4-S10, S12, C4, C5 | ecrits ou codes | docs, code |
| S13, S14 | idees / regles abandonnees | fichiers |
| **Trades manuels de Jackson** (Asie, niveau DEFENDU, 123 trades Bot 3 V3) | **reel** | **INTROUVABLE dans les deux depots** |

**C'est le point le plus important de l'inventaire.** Les seuls trades reels
connus ne sont pas dans le code. Ce que Jackson a trade a la main est dans les
revues de session, le journal, ou sa memoire.

---

## 6. MOTIFS D'ABANDON ECRITS — a ne pas retester tels quels

- **RuleEngine** (S8, S10, S14) : *« IF/ELSE ne capture pas la complexite du marche → attendre le ML »* ; 3 jours de donnees.
- **BN V5, Bot 3 v4, Bot 4 v1** : PATTERN_11, cascade de filtres.
- **Systeme de decembre** (S13 en bloc) : 134 trades, WR 21,6 %, −2 875 $ ; portes ouvertes une a une pour obtenir des trades.
- **VWAP-SD B** : *« EDGE INVERSE LIVE »*, PF 0,52 sur 8 jours.
- **VWAP-SD D** : *« n=13 insuffisant statistiquement »*.
- **TP/SL fixes en ticks** (V1_NOTES : SL 25 t / TP 30 t NQ, SL 12 t / TP 28 t ES) : valides sur un autre systeme, unites non transposables.

---

## 7. COLONNES QUI ONT CHANGE — a corriger avant d'ecrire une hypothese

| Setup | Colonne | Etat | Remplacante |
|---|---|---|---|
| S3 | `va_position_pct` | **C**, nulls 53 % | `inside_cur_va` (A) + `dist_cur_vah/val` (A) |
| S2 | `range_pos` | **C** | — |
| S2 | `rvol_absorb_*` | **R**, ~1 % | evenement rare, N faible attendu |
| S4 | `momentum_5b` | etait un **lag 2** | `momentum_5b_r` (A) — **recalibrage = cycle suivant** |
| S8, S10 | `dist_prev_vwap` | faux (fuseau) | `dist_prev_vwap_rth_r` (A) |
| S9 | `dist_asia_high` | **n'existe pas** | `dist_asia_high_pct` est en C, signe inverse |
| S1 | `dist_mq_call_0dte` | B, hors noyau | `dist_mq_call` (B, dans le noyau) |
| S13/JG | `composite_poc_*` | **C**, vide a 99 % | aucune |
| S11 | `bn_absorb_*`, `bn_color_*_2` | **B** (reclassees) | — |

---

## 8. CE QUI RESTE INTROUVABLE

- Les **trades manuels** de Jackson avec leur raison — dans aucun des deux depots.
- `LOGS/setups_observed/*_setups_trades.jsonl`, cite par `DOCS/SETUP_PERFORMANCE_REPORT.md` : non ouvert.
- Les **revues de session** detaillees et les backtests jour par jour.
- Les conversations passees.

---

## 9. POUR CHOISIR LES DIX — observations, sans recommandation

1. **Cinq des neuf setups proposes par Fable ont un equivalent deja teste et NO-GO** sur 24 mois : S3≈H5, S8≈H1, S6≈SF, S10≈JM, S1≈H4. Sur une autre barriere et d'autres donnees — donc a reprendre en connaissance de cause, pas a ecarter.
2. **Deux setups n'ont aucun equivalent teste** : S2 (absorption RVOL) et S9 (sweep + reprise). S9 a deja une version codee dans le depot courant (C4).
3. **Trois setups portent un resultat positif ecrit et recent** : C1-A (PF 2,26 / 26,00 avec confluence, 8 j), C3 Bearish_Rejection (PF 5,05, N=55, 14 j), C2 avec filtre qualite (PF 2,62, 12 trades sur 37). Effectifs faibles, periodes courtes.
4. **Un setup est bloque par ses colonnes** : S3, tant qu'il n'est pas reecrit sur `inside_cur_va` + `dist_cur_vah/val`.
5. **La structure par regime du paradigme est la seule qui vienne de Jackson** et qui ait survecu a toutes les versions. Elle se superpose exactement a L2 → L3 → L4.
6. **La dixieme hypothese n'est dans aucun depot.** Elle doit venir des trades reels — le niveau DEFENDU, ou ce qui a ete trade en Asie.
