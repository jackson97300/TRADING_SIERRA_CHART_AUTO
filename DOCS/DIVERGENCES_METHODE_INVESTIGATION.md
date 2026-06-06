# Audit DIVERGENCES-METHODE — 37 features Sierra DMP vs Python live_enriched

Date : 2026-06-06
Source verite Python : `live_cache.read_bar` (Databento OHLCV) + `vix_lite_reader` (Sierra JSONL VIX) + `load_mq_levels` (Sierra MQ).
Source verite C++ : `CPP/MIA_REFACTORED/DUMPER/DMP_*.h` (Sierra bars + Sierra studies + Sierra MQ).

## Resume executif

- 37 features auditees.
- SIERRA = 14 (source verite : C++ uniquement, Python ne calcule pas ou recoit NULL).
- PYTHON = 0 (aucun cas ou C++ a un bug et Python est correct seul).
- DEPEND-USAGE = 18 (formules valides des deux cotes, choix selon norm/clamp/timeframe).
- INVESTIGATION-PROFONDE = 5 (formule pas localisable ou logique sensiblement different — verification empirique requise).

Differences structurelles a retenir :
1. **CLAMP ATR ±5** : `CalcDistATR` C++ clampe systematiquement, Python (post fix P4 V4 15/05) ne clampe PAS. Train-serve skew si C++ utilise.
2. **range_pos** : C++ = position dans VA session (cur_val-cur_vah), Python enricher = position dans la barre 1min (low-high). BUG-PYTHON nom collision.
3. **bn_*, rotation_***, **retest_*** : Python ne sait PAS les calculer en mode Databento (depend des etudes Sierra ACSIL). Source unique = Sierra.

## Group A — VWAP (5)

### dist_vwap_d
- **Sierra** : `DMP_Transform.h:536` `f.dist_vwap_d = (r.vwap_day - r.price_close) / tick_size`. Unite : TICKS.
- **Python** : non-recalcule. Lit `dist_vwap_d` du payload upstream (Databento ne fournit pas vwap_day, donc NULL en mode Databento).
- **Difference** : SOURCE-DEPENDANT. En mode "Python branche sur Sierra", Python relit le `dist_vwap_d` Sierra. En mode pure Databento, NULL.
- **Source verite** : SIERRA. Le VWAP-journalier est calcule par Sierra, Python ne l'a pas natif.
- **Justification** : VWAP_day necessite tick-by-tick volume accumule depuis open RTH. Databento OHLCV 1m ne suffit pas.

### dist_vwap_d_atr
- **Sierra** : `DMP_Transform.h:537` `CalcDistATR(d_d, atr_ticks)` AVEC CLAMP `±DMP_ATR_CLIP` (=5).
- **Python** : `enricher_chain.py:820-870` (Pass P4 V4) recalcule `(vwap_d - close) / tick / atr_ticks` SANS CLAMP (mean 8.4, max 222 sur batch NQ).
- **Difference** : METHODE-DIFFERENTE (clamp ±5 vs non-clampe). Convention parquet v4 = NON CLAMPE.
- **Source verite** : PYTHON (convention batch v4 alignee, evite train-serve skew documente lignes 820-827).
- **Justification** : `enricher_chain.py:824-826` declare explicitement : "V1-V3 clampaient → 70% bars saturees, 12/17 features mortes". Sierra DMP devrait s'aligner en retirant CLAMP.

### dist_vwap_w_atr
- **Sierra** : `DMP_Transform.h:547` `CalcDistATR(d_w, atr_ticks)` CLAMP.
- **Python** : `enricher_chain.py:843-869` (P4 V4) non clampe.
- **Difference** : idem dist_vwap_d_atr. METHODE-DIFFERENTE.
- **Source verite** : PYTHON (parite batch v4).
- **Justification** : meme raisonnement, anti train-serve skew.

### dist_vwap_m_atr
- **Sierra** : `DMP_Transform.h:553` `CalcDistATR(d_m, atr_ticks)` CLAMP.
- **Python** : `enricher_chain.py:843-869` (P4 V4) non clampe.
- **Difference** : METHODE-DIFFERENTE.
- **Source verite** : PYTHON.
- **Justification** : parite batch v4.

### vwap_slope_10
- **Sierra** : `DMP_Reader.h:1224` `(vwap_day - vwap_day(t-10)) / 3.0f`. Unite : points / barre. Anomalie : divise par 3.0 et non par 10. Lecture vwap_now - vwap il y a 3 barres.
- **Python** : non recalcule. Lu directement du JSONL DMP via `rolling_features.py:128`.
- **Difference** : SOURCE-DEPENDANT. Le C++ a une division potentiellement bugue (le commentaire dit "/10" mais divise par 3).
- **Source verite** : INVESTIGATION-PROFONDE. La constante `3.0f` vs nom `vwap_slope_10` necessite verification ce qu'on veut (slope sur 10 bars ou pas).
- **Justification** : commentaire C++ `pts/barre` mais divise par 3 = inconsistent. Possible bug C++ ; a verifier que `vwap_slope_30` (/10.0) suit la meme logique.

## Group B — VIX (3)

### dist_vix_put
- **Sierra** : `DMP_Transform.h:785` `f.dist_vix_put = r.vix_put - r.vix_level`. Unite : points VIX.
- **Python** : `vix_lite_reader.py:232` `out["dist_vix_put"] = vix_put - vix_level`. Idem unite.
- **Difference** : EQUIVALENT (formule strictement identique, source identique Sierra JSONL VIX).
- **Source verite** : DEPEND-USAGE (les deux corrects).
- **Justification** : faux DIVERGENT. Verifier que l'audit V2 a bien compare la meme colonne (drift potentiel sur ts).

### dist_vix_hvl
- **Sierra** : `DMP_Transform.h:762-764` `r.vix_hvl - r.vix_level`.
- **Python** : `vix_lite_reader.py:233` idem.
- **Difference** : EQUIVALENT.
- **Source verite** : DEPEND-USAGE.
- **Justification** : faux DIVERGENT. Causes possibles : (a) lecture VIX desynchro entre DMP et JSONL VIX Lite, (b) fallback `vix_hvl_0dte -> vix_hvl` cote C++ ligne 807-808.

### dist_vix_hvl_0dte
- **Sierra** : `DMP_Transform.h:791-792` `r.vix_hvl_0dte - r.vix_level` AVEC fallback `r.vix_hvl - r.vix_level` si 0DTE invalide (ligne 807-808).
- **Python** : `vix_lite_reader.py:236` `vix_hvl_0dte - vix_level` SANS fallback explicite.
- **Difference** : METHODE-DIFFERENTE (fallback C++ vs strict Python). Quand sg7 vide (VIX calme), C++ recopie sg2 ; Python laisse NaN.
- **Source verite** : SIERRA (fallback documente ligne 794-803 anti-fusion-niveaux MenthorQ).
- **Justification** : Python doit reprendre ce fallback sinon dist_vix_hvl_0dte = NaN sur sessions VIX calme = features mortes.

## Group C — Volume Profile (8)

### dist_prev_vpoc_atr
- **Sierra** : `DMP_Transform.h:661-662` `CalcDistATR(d_pvpoc, atr_ticks)` CLAMP ±5.
- **Python** : `enricher_chain.py:853-869` (P4 V4) non clampe.
- **Difference** : METHODE-DIFFERENTE.
- **Source verite** : PYTHON.
- **Justification** : parite batch v4.

### dist_cur_vah / dist_cur_val / dist_cur_vpoc
- **Sierra** : `DMP_Transform.h:629-631` `CalcDistTicks(level, p, ts)` = `(level - close) / tick`. TICKS.
- **Python** : non recalcule. Lit `dist_cur_vpoc` du JSONL DMP. Si pure Databento, NULL (VPOC besoin VAP intra-day).
- **Difference** : SOURCE-DEPENDANT.
- **Source verite** : SIERRA. VAP session necessite cellules tick-level volume.
- **Justification** : Databento ne fournit pas VAP. Si Python branche sur Sierra : equivalent. Si Python pure Databento : NULL = trou critique pour Bot 3.

### va_position_pct
- **Sierra** : `DMP_Transform.h:635` `PosInRange(p, cur_val, cur_vah)` retourne DMP_INVALID hors range (fix 2026-04-16, anti-pollution -1).
- **Python** : non recalcule. Lit du JSONL DMP. Si Databento pure : NULL.
- **Difference** : SOURCE-DEPENDANT.
- **Source verite** : SIERRA.
- **Justification** : depend de VAP session.

### poc_position
- **Sierra** : `DMP_Transform.h:459` "Position du POC dans le range [0=bas, 0.5=mid, 1=haut]" ; init 0.5 ligne 1572. Calcule via Profile Shape (DMP_ProfileShape.h).
- **Python** : non localise dans enricher Python.
- **Difference** : SOURCE-DEPENDANT.
- **Source verite** : SIERRA (necessite cellules VAP pour POC location intra-VA).
- **Justification** : impossible avec OHLCV pur.

### range_pos
- **Sierra** : `DMP_Transform.h:642-644` `(price - cur_val) / (cur_vah - cur_val) * 100` clampe 0-100 — **position dans la VA session**.
- **Python** : `enricher_chain.py:739` `(close - low) / (high - low)` — **position dans la barre 1min**.
- **Difference** : BUG-PYTHON (collision de nom, semantiques opposees).
- **Source verite** : SIERRA (semantique originelle).
- **Justification** : `enricher_chain.py:1370` commentaire avoue le piege : "NE PAS utiliser range_pos/100 (= bar 1min, semantique fausse)". Le Python ECRASE le range_pos Sierra avec une valeur barre-1min. Bug confirme — renommer `range_pos_bar` cote Python ou ne pas ecraser.

### inside_cur_va
- **Sierra** : `DMP_Transform.h:638` `DMP_IsValid(va_position_pct) ? 1 : 0`. Booleen pur.
- **Python** : non recalcule. Lit JSONL DMP. NULL si Databento pure.
- **Difference** : SOURCE-DEPENDANT.
- **Source verite** : SIERRA.
- **Justification** : depend de VA session.

## Group D — Sessions / IB (3)

### dist_sess_high / dist_sess_low
- **Sierra** : `DMP_Transform.h:875-876` `CalcDistTicks(sess_high/low, p, ts)`. TICKS.
- **Python** : `phase_b_helpers.py:579-587` `dist_sess_high_pct = (sess_high - close) / close * 100`. **PCT**.
- **Difference** : UNITE (ticks vs %).
- **Source verite** : DEPEND-USAGE. Audit V2 probable false positif si comparait `dist_sess_high` (ticks) vs `dist_sess_high_pct` (pct). Verifier que l'audit lisait bien la meme colonne nominale.
- **Justification** : Python ecrit `dist_sess_high_pct`, pas `dist_sess_high`. Si audit comparait `dist_sess_high` (les deux contiennent le meme nom mais Python le copie potentiellement non-recalcule), c'est OK. Sinon = UNITE incompatible.

### sess_range_atr
- **Sierra** : `DMP_Transform.h:883` `(sess_high - sess_low) / atr_ticks`.
- **Python** : `enricher_chain.py:1417-1419` `(sess_high - sess_low) / tick_size / atr_daily_ticks`. Identique.
- **Difference** : EQUIVALENT.
- **Source verite** : DEPEND-USAGE.
- **Justification** : faux DIVERGENT probable.

## Group E — Game Changers Dalton (4)

### open_type / open_zone / open_bias_conf / open_direction
- **Sierra** : `DMP_OpenType.h` (~700 LOC, ENUM 12 valeurs OT, 7 zones).
- **Python** : `game_changers.py` declare en header (l.9-10) "PORT exact de DMP_OpenType.h §4-§5". Fonctions `classify_open_type`, `classify_open_zone`, `direction`, `confidence`.
- **Difference** : METHODE-DIFFERENTE en source (open_cash, ib_high, ib_low) + EQUIVALENT en algo.
- **Source verite** : DEPEND-USAGE. Python PORT valide en theorie, mais necessite **open_cash, ib_high, ib_low** = inputs Sierra.
- **Justification** : Python ne peut calculer open_type que si ces 3 inputs sont disponibles. Databento OHLCV 1min permet open_cash, mais IB high/low necessite agregation 10:00-11:00 ET = facile en streaming. Faisable cote Python avec port direct. CONFIRMER que `game_changers_streaming` est appele dans `live_enricher` (sinon = NULL).

## Group F — Battle Navale (2)

### bn_absorb_ask / bn_absorb_bid
- **Sierra** : `DMP_Reader.h:1069-1071` `DMP_ReadExtensionLineCount(sc, chart, ABSORB_ASK_id)` puis `SafeBool` dans `DMP_Transform.h:934-935`. Lit etude ACSIL "Absorption High/Low" via Extension Lines.
- **Python** : aucune occurrence dans enricher. **Pas de calcul Python**.
- **Difference** : METHODE-DIFFERENTE — Python ne peut pas calculer ces features (depend etude ACSIL Sierra avec drawing Extension Lines until Future Intersection).
- **Source verite** : SIERRA (irremplacable cote Databento).
- **Justification** : signal pure ACSIL ; sans Sierra, ces 2 features = mortes pour Bot 3.

## Group G — RVOL (4)

### rvol_buy / rvol_sell / rvol_absorb_buy / rvol_absorb_sell
- **Sierra** : `DMP_Pipeline.h:574-585` :
  ```
  if (rvol>=SPIKE) {
    if (delta_pct>0.05) rvol_buy=1;
    if (delta_pct<-0.05) rvol_sell=1;
    if (delta_pct<-0.05 && finish>20) rvol_absorb_buy=1;
    if (delta_pct>0.05 && finish<-20) rvol_absorb_sell=1;
  }
  ```
- **Python** : `rvol.py:130-166` formules **STRICTEMENT IDENTIQUES**.
- **Difference** : EQUIVALENT en algo. La divergence empirique = inputs differents (delta_pct/finish_strength viennent de footprint Sierra cote C++, mais de `(close-open)/range*100` cote Python `phase_b_helpers.py:1363`).
- **Source verite** : SIERRA pour rvol_*_strong (necessite finish_strength footprint vrai). Pour rvol_buy/sell simples (juste delta_pct), DEPEND-USAGE.
- **Justification** : `finish_strength` Python = approximation OHLC, vs C++ = Ask-Bid finish footprint reel. Asymetrie qui explique rvol_absorb_* false positif.

## Group H — Patterns (5)

### rotation_up / rotation_dn
- **Sierra** : `DMP_Reader.h:1254-1255` `DMP_ReadBN_Event(sc, chart, rup_id/rdn_id)`. Lit etude ACSIL rotation BN.
- **Python** : aucune occurrence.
- **Difference** : SOURCE-DEPENDANT — Python ne calcule pas.
- **Source verite** : SIERRA.
- **Justification** : depend etude ACSIL Battle Navale.

### retest_high_delta_div / retest_low_delta_div
- **Sierra** : `DMP_Pipeline.h:374` `retest_high_delta_div = (fpbs_cvd_day < delta_at_sh) ? 1 : 0`. Compare CVD day actuel vs CVD enregistre au swing high.
- **Python** : `enricher_chain.py:930` `retest_high_delta_div = 1 if (is_retest_h and delta_div_sell==1) else 0`. Combine retest detecte + delta_div_sell.
- **Difference** : METHODE-DIFFERENTE (C++ = comparaison CVD, Python = combo retest + div_sell). Logique conceptuelle similaire (divergence au retest) mais formules differentes.
- **Source verite** : INVESTIGATION-PROFONDE. Necessite verifier laquelle correle mieux empiriquement avec reversal posterieurs.
- **Justification** : approches valides toutes deux mais pas equivalentes numeriquement.

### bool_gex_flip_zone
- **Sierra** : `DMP_Writer.h:658` "bool_gex_flip_zone". Source : `DMP_Transform.h` calcule = 1 si dans zone flip GEX.
- **Python** : `enricher_chain.py:231` `payload["bool_gex_flip_zone"] = 1 - mq_gamma_condition`. Recalcule simplement.
- **Difference** : INVESTIGATION-PROFONDE — formule C++ non localisee precisement. Verifier la definition exacte cote Transform.
- **Source verite** : INVESTIGATION-PROFONDE.
- **Justification** : Python pratique mais simpliste (negation de gamma_condition) ; C++ peut etre plus sophistique.

## Group I — Misc (3)

### momentum_5b
- **Sierra** : `DMP_Pipeline.h:281` `momentum_5b = price_close - price_close(i-5)`. POINTS.
- **Python** : non localise dans enricher.
- **Difference** : SOURCE-DEPENDANT.
- **Source verite** : SIERRA si non calcule cote Python. Sinon DEPEND-USAGE (formule triviale, Python peut le faire).
- **Justification** : INVESTIGATION-PROFONDE — check si rolling_features Python le recree.

### finish_strength
- **Sierra** : `DMP_Transform.h:1000` `f.finish_strength = r.fpbs_finish` (footprint Ask-Bid % cloture barre). Vrai indicateur footprint.
- **Python** : `phase_b_helpers.py:1294,1363` `finish_strength = (close - open) / range_size * 100`. **Approximation OHLC, pas footprint reel**.
- **Difference** : METHODE-DIFFERENTE (footprint Ask-Bid vs OHLC range).
- **Source verite** : SIERRA (vraie semantique). Python = proxy degrade.
- **Justification** : finish_strength footprint mesure agressivite Ask cote close ; (close-open)/range mesure simplement direction de la barre. Pas la meme info. CRITIQUE : rvol_*_strong et rvol_absorb_* Python = signaux degrades. Cote Bot 3, c'est un trou edge.

### vix_above_hvl_0dte
- **Sierra** : `DMP_Transform.h:811-814` utilise `hvl_eff = vix_hvl_0dte || vix_hvl`. Booleen avec fallback.
- **Python** : `vix_lite_reader.py:243-244` `compute_vix_above_hvl(vl, vix_hvl_0dte)`. SANS fallback.
- **Difference** : METHODE-DIFFERENTE (fallback vs strict).
- **Source verite** : SIERRA (fallback documente).
- **Justification** : meme que dist_vix_hvl_0dte. Python doit aligner.

## Synthese decisions

| Feature | Source verite | Bref |
|---|---|---|
| dist_vwap_d | SIERRA | VWAP day necessite tick-volume, pas dans Databento |
| dist_vwap_d_atr | PYTHON | Anti train-serve skew (sans CLAMP) |
| dist_vwap_w_atr | PYTHON | Parite batch v4 |
| dist_vwap_m_atr | PYTHON | Parite batch v4 |
| vwap_slope_10 | INVESTIGATION-PROFONDE | Constante /3.0f C++ vs nom_10 suspect |
| dist_vix_put | DEPEND-USAGE | Formules identiques |
| dist_vix_hvl | DEPEND-USAGE | Formules identiques |
| dist_vix_hvl_0dte | SIERRA | Fallback critique en VIX calme |
| dist_prev_vpoc_atr | PYTHON | Anti CLAMP |
| dist_cur_vah | SIERRA | VAP session = pas dans Databento |
| dist_cur_val | SIERRA | idem |
| dist_cur_vpoc | SIERRA | idem |
| va_position_pct | SIERRA | depend VAP |
| poc_position | SIERRA | depend VAP+Profile Shape |
| range_pos | SIERRA | BUG-PYTHON : range bar 1min ecrase range VA session |
| inside_cur_va | SIERRA | depend VAP |
| dist_sess_high | DEPEND-USAGE | UNITE differente (ticks vs pct) |
| dist_sess_low | DEPEND-USAGE | UNITE differente |
| sess_range_atr | DEPEND-USAGE | Formules equivalentes |
| open_type | DEPEND-USAGE | Python = port direct C++ |
| open_zone | DEPEND-USAGE | idem |
| open_bias_conf | DEPEND-USAGE | idem |
| open_direction | DEPEND-USAGE | idem |
| bn_absorb_ask | SIERRA | etude ACSIL pure, irremplacable |
| bn_absorb_bid | SIERRA | idem |
| rvol_buy | DEPEND-USAGE | Algo identique, inputs differents |
| rvol_sell | DEPEND-USAGE | idem |
| rvol_absorb_buy | SIERRA | finish_strength footprint requis |
| rvol_absorb_sell | SIERRA | finish_strength footprint requis |
| rotation_up | SIERRA | etude ACSIL BN |
| rotation_dn | SIERRA | idem |
| retest_high_delta_div | INVESTIGATION-PROFONDE | Logiques differentes |
| retest_low_delta_div | INVESTIGATION-PROFONDE | idem |
| bool_gex_flip_zone | INVESTIGATION-PROFONDE | Formule C++ exacte a localiser |
| momentum_5b | INVESTIGATION-PROFONDE | Calcul Python a confirmer |
| finish_strength | SIERRA | Footprint Ask-Bid, pas OHLC range |
| vix_above_hvl_0dte | SIERRA | Fallback critique |

## Actions recommandees

1. **CLAMP ATR** : aligner C++ DMP sur convention batch v4 (retirer `DMP_ATR_CLIP` sur tous `CalcDistATR`). Sinon Bot 1/3 lit clamp partiel = features 70% saturees.
2. **range_pos** : Python `enricher_chain.py:739` ne doit PAS ecraser `range_pos`. Renommer en `range_pos_bar` ou skip si valeur Sierra presente. Bug confirme par commentaire ligne 1370.
3. **vix_above_hvl_0dte / dist_vix_hvl_0dte** : porter fallback `hvl_0dte || hvl` cote Python `vix_lite_reader`.
4. **finish_strength** : decision strategique. Si pivot Sierra-source, alors finish_strength Python obsolete = degrader rvol_absorb_*. Si pivot Databento, accepter le proxy OHLC.
5. **bn_absorb_*, rotation_***, VAP-derives (VPOC/VAH/VAL/va_position_pct/poc_position) : SI Python pivot Databento, ces 14 features = NULL. Trou strategique pour Bot 3 narrative. Plan B = re-router Sierra pour ces inputs uniquement.
6. **vwap_slope_10** : investigation C++ — la constante `/3.0f` ligne 1224 contredit le nom `_10`. Possible bug latent C++.
