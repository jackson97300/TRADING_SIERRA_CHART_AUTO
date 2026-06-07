# Review #2 quality-validator — Batch B3 (F22+F12+F8+F9, 29 features)

Date : 2026-06-07
Reviewer : quality-validator (review #2 sur code C++ B3 PRE-deploy)
Schema cible : 3.7.20 (376 columns, +29 vs 347 B2)
Status B3 : **NON deploye** — validation theorique sur code C++ + Python live_enriched substitution

---

## Verdict review #2 quality-validator B3

- **VERDICT : NOGO**
- **Score : 4/10**

Le code C++ est techniquement propre (helpers fail-loud, clamps OK, PersistVars
bien isoles, reset Full Recalc present, DMP_INVALID propagation correcte). Les
formules F22 et F8 sont strictement equivalentes au Python, tres bonne facture.

MAIS sur F12 il y a **deux divergences semantiques majeures** sur 4 features
(long_up_bar, long_dn_bar, long_dn_up_pattern, long_up_dn_pattern) qui mesurent
des choses TOTALEMENT DIFFERENTES du Python. Le commentaire C++ qui annonce
"reuse Python" est faussement rassurant : il pointe vers `phase_b_plus_streaming.py:499-505`
qui n'existe pas (le fichier fait 489 lignes, et long_up_bar n'est pas dans le
streaming Python). Le vrai code Python est dans `phase_b_plus_engine.py:272-282`
et utilise la formule Sierra officielle Jackson 27/04/2026 :

  ```
  Python long_up_bar = (O > C[-1]) AND (H > L[-1] + threshold_ticks)
                       avec threshold_ticks = 12 ES / 24 NQ
  ```

Le C++ B3 utilise :

  ```
  C++ long_up_bar = (close > open) AND (|close - open| > 2 * ATR_points)
  ```

**Preuve empirique** sur NQ 02/06/2026 (1380 bars) :
- Python long_up_bar : **390 fires (28.26%)**
- C++ B3 long_up_bar simulee : **3 fires (0.22%)**
- Divergence x130. ML downstream verra deux features qui s'appellent pareil
  mais ne mesurent pas la meme chose. Backtests historiques (parquet v4 base
  Python) deviendraient inexploitables pour Bot 3 si le bot lit le DMP live.

Cumule avec la divergence patterns shift-1 (Python = 3-bar formule per-symbole
ES/NQ avec lookahead [+1] ES ou shift NQ ; C++ = simple AND `long_up_bar[t-1] ET
long_dn_bar[t]`), 5 features F12 sur 10 sont semantiquement fausses vs Python.

C'est un **incident COMMENT_FALSE** caracterise (cf categorie incident_log) :
le commentaire C++ ligne 24 affirme "reuse formule Python" alors que la
formule est inventee. Pattern 11 V1 (audit superficiel forme = formule).

NOGO bloquant cote ML mais review pertinente sur les autres familles (F22,
F8, F9 GO, F12 sub-features OK : bar_body_pct, bar_body_ticks, wicks, range_size).

---

## Code C++ verdict

- **Note (sur 10) : 6/10**

Justification :
- **+** Helpers fail-loud (DMP_F22_IsInvalid, DMP_F12_IsInvalid, DMP_F8_IsInvalid,
  DMP_F9_IsInvalid) tous strictement reproduits — pas de masquage NaN/Inf.
- **+** Clamps respectes : pct_in_range [0, 100] (ligne 78-79), position_in_range
  [0, 1] (91-92), wicks [0, 3] (183, 199), bar_body_pct [-100, 100] (155-156).
- **+** DMP_INVALID propage correctement (F22 premium/discount valide a parent
  pct_in_range, F8 tous champs INVALID si mins_et hors plage).
- **+** PersistVars 205-210 documentes en clair + reset Full Recalc Index 0
  present (F12 lignes 237-240, F9 lignes 121-126).
- **+** F22 discount_zone mirror strict avec premium_zone : sanity confirme
  0/6 mirror violations sur 6 jours.
- **+** F8 mins_since/to_next utilise DMP_INVALID (pas -1) — corrige une
  regression Python -1 sentinel qui leak.
- **+** F9 manual_switch protection via 2-letter root code (`ESM26` vs `NQM26`
  detectes, root different = NE PAS flagger). Algo correct.
- **+** F8 mins_to_next utilise `>` strict (pas `>=`), correct (event = is_news_HHMM).
- **+** Writer columns array = 376 (verifie programmatiquement), coherent avec
  n_columns annonce ligne 574. Last 8 cols dans l'ordre attendu.
- **-** F12 long_up_bar / long_dn_bar : **formule DIFFERENTE du Python**
  (ATR-multiple vs SC bar+threshold).
- **-** F12 long_dn_up_pattern / long_up_dn_pattern : **formule SIMPLIFIEE**
  (2-bar AND vs 3-bar formule per-symbole ES/NQ Python).
- **-** Commentaire F12 ligne 24 pointe vers `phase_b_plus_streaming.py:499-505`
  qui n'existe pas (le fichier a 489 lignes). Pattern COMMENT_FALSE.
- **-** F12 bar_no_trade : Python = `delta_bar.isna()` (strict NaN), C++ B3 =
  `|delta| < 0.5 OR INVALID`. Divergence mineure (~19 bars sur 1380 = 1.4%) mais
  reelle.
- **-** Config.h commentaire ligne 97 dit "+28 fields" alors que Writer
  serialise 29 (4+10+14+1). Coquille post-Jackson-rectif 22:50 non propagee.
  Pas bloquant (le code se compile, n_columns=376 = correct), mais documentation
  desynchronisee.

---

## Stats par famille

| Famille | Features | Code OK | Sanity OK | Verdict |
|---|---|---|---|---|
| **F22** | 4 | 4/4 | 4/4 (mirror strict 0 violations sur 6 jours, ranges [0,100] et [0,1] respectes 100% des bars) | **GO** |
| **F12** | 10 | 5/10 | 5/10 (4 features divergence semantique majeure + 1 mineure) | **NOGO** |
| **F8** | 14 | 14/14 | 14/14 (logique horaire pure, sentinelle DMP_INVALID OK, fires 1/bar pour news_715/930 confirmes) | **GO** |
| **F9** | 1 | 1/1 | 1/1 (0 fires hors trimestre rollover normal, manual_switch protection correcte) | **GO** |

---

## Bugs trouves

### BUG #1 — F12 long_up_bar / long_dn_bar : formule DIVERGENTE du Python (CRITIQUE)

- **Fichier** : `CPP/MIA_REFACTORED/DUMPER/DMP_F12_BarShape.h:218-225` + `DMP_F12_LongBar` helper:92-105
- **Symptome** : la formule C++ est `(close - open) > 2 * ATR_points` avec sign check,
  alors que la formule Python officielle Sierra (Jackson 27/04/2026, validee 7 mois
  parquets v4) est `(O > C[-1]) AND (H > L[-1] + threshold_ticks)` avec threshold
  per-symbole (12 ES, 24 NQ).
- **Preuve empirique** :
  - NQ 02/06/2026 : Python = 390 fires (28.26%) vs C++ B3 = 3 fires (0.22%) → x130
  - ES 27/05/2026 : Python ~ 0.8-4% selon jour. C++ B3 different.
- **Risque** : ML voit une feature qui s'appelle `long_up_bar` mais ne mesure pas
  la meme chose que le parquet historique. Bot 3 `long_up_bar` consumer cassera.
- **Cause** : commentaire C++ ligne 22-24 cite `phase_b_plus_streaming.py:499-505`
  qui n'existe pas (fichier 489 lignes, et long_up_bar absent du streaming).
  Le code-writer a invente une formule par defaut sans verifier le source canonique
  (`phase_b_plus_engine.py:272-282`).
- **Fix obligatoire** :
  ```cpp
  // Lire close[t-1], high[t], low[t-1] depuis PersistVars ou r.price_close_prev
  // (a exposer dans DMP_RawData). Utiliser threshold_ticks per-symbole :
  // ES = 12, NQ = 24 (LONG_BAR_THRESHOLD_TICKS Python).
  bool sign_up = open > close_prev;
  bool size_up = high > low_prev + threshold_ticks * tick_size;
  return (sign_up && size_up) ? 1.0f : 0.0f;
  ```
- **Verdict** : NOGO bloquant. Refactor F12 long_*_bar.

### BUG #2 — F12 long_dn_up_pattern / long_up_dn_pattern : formule SIMPLIFIEE (CRITIQUE)

- **Fichier** : `CPP/MIA_REFACTORED/DUMPER/DMP_F12_BarShape.h:248-263`
- **Symptome** : C++ = `prev_long_dn AND cur_long_up`, sans verifier les 3-bar
  patterns Python avec lookahead per-symbole ES/NQ (cf `phase_b_plus_engine.py:417-451`).
- **Risque** : feature qui s'appelle `long_dn_up_pattern` mais ne represente
  pas le pattern reversal 3-bar Python. Bot 3 `pattern` consumer faux.
- **Note bonus** : Python ES utilise lookahead `[+1]` (`o_next`, `c_next`, `h_next`,
  `l_next` shift(-1)). En live streaming Sierra, le `[+1]` n'existe pas (LIVE = pas de
  bar future). Donc le port C++ live ne peut PAS reproduire bit-for-bit la formule
  ES Python — c'est un compromis architecture acceptable, mais documente. NQ
  formule sans lookahead = portable en live.
- **Fix obligatoire** :
  ```cpp
  // NQ (sans lookahead) : O[-1]<C[-2], H[-2]>L[-1]+40t, O>C[-1], H>L[-1]+40t, H>H[-1]
  // -> Requiert 3 bars d'historique OHLC PersistVars ou r.price_*_prev/prev2.
  // ES (avec lookahead) : impossible en live exactement -> documenter divergence
  // dans commentaire F12 + accepter shift +1 vs Python (1 bar de delay).
  ```
- **Verdict** : NOGO bloquant. Refactor F12 patterns.

### BUG #3 — F12 bar_no_trade formule MINEURE differente (RESERVE)

- **Fichier** : `CPP/MIA_REFACTORED/DUMPER/DMP_F12_BarShape.h:209-215`
- **Symptome** : Python = `delta_bar.isna()` (strict NaN), C++ B3 = `|delta| < 0.5
  OR DMP_INVALID`. Sur 1380 bars NQ 02/06 : Python = 0 fires, C++ B3 ~ 19 fires (1.4%).
- **Justification C++** : commentaire ligne 213 ("garde anti-arrondi flottant").
  Choix design plus permissif, mais ne match pas Python.
- **Risque** : faible (Python 0 fires = donnees liquides, C++ 1-2% fires = bars
  faibles activite). ML pourrait apprendre signal supplementaire.
- **Fix recommande** : aligner sur Python `delta_bar.isna()` strict :
  ```cpp
  f.bar_no_trade = DMP_F12_IsInvalid(r.fpbs_delta) ? 1.0f : 0.0f;
  ```
- **Verdict** : GO-AVEC-RESERVES. Aligner sur Python pour parite stricte.

### BUG #4 — F12 commentaires source FAUX (DOCUMENTATION)

- **Fichier** : `CPP/MIA_REFACTORED/DUMPER/DMP_F12_BarShape.h:22-25`
- **Symptome** : commentaire pointe vers `phase_b_plus_streaming.py:499-505` qui
  n'existe pas (fichier 489 lignes, et `long_up_bar` n'est pas dans streaming).
  Le vrai source est `phase_b_plus_engine.py:272-282` (batch).
- **Cause** : pattern COMMENT_FALSE — code-writer a fabrique une reference fausse
  qui a faussement rassure la review #1.
- **Fix obligatoire** : corriger les references et expliquer la divergence
  formule explicitement.
- **Verdict** : RESERVE bloquant (induit en erreur les reviewers futurs).

### BUG #5 — Config.h commentaire desynchronise (DOCUMENTATION)

- **Fichier** : `CPP/MIA_REFACTORED/DUMPER/DMP_Config.h:97-99`
- **Symptome** : "+28 fields struct + 4 includes B3 + 4 appels" et "n_cols 347 ->
  375" alors que avec Jackson rectif (discount_zone GARDE) c'est +29 et 376.
- **Risque** : faible (le code se compile, n_columns=376 est correct dans Writer
  ligne 574). Mais reviewers futurs verront des chiffres incoherents.
- **Fix recommande** : corriger 375 -> 376 et 28 -> 29 dans les commentaires Config.h.
- **Verdict** : RESERVE (cosmetique, non-bloquant).

---

## Conditions de deploy

### Pour passer NOGO -> GO

1. **F12 long_up_bar / long_dn_bar** : reecrire formule selon Python
   `phase_b_plus_engine.py:272-282`. Necessite exposition de `close_prev`,
   `low_prev` dans DMP_RawData via PersistVars 211-212 (libres).
2. **F12 long_dn_up_pattern / long_up_dn_pattern** : reecrire formule 3-bar
   per-symbole selon `phase_b_plus_engine.py:417-451`. Documenter la
   limitation ES (lookahead `[+1]` impossible en live, shift +1 vs Python).
3. **F12 bar_no_trade** : aligner sur Python strict `isna()` :
   `DMP_F12_IsInvalid(r.fpbs_delta) ? 1.0f : 0.0f`.
4. **Commentaires** : corriger DMP_F12_BarShape.h:22-25 et DMP_Config.h:97-99
   pour eviter incident COMMENT_FALSE re-occurrence.
5. **Test parity** : ajouter dans `tools/test_parity_B3.py` un check qui compare
   les **fire rates** Python vs C++ pour long_up_bar/dn_bar/patterns. Si
   ecart > 5pp -> FAIL test. Sans ce test, on n'aurait pas detecte le bug
   (le test_parity_B3 actuel ne fait que sanity checks range/boolean, pas
   parite Python).
6. **Pre-deploy** : recompiler DLL Sierra + Reload Studies, NE PAS Reload Charts
   (cf regle "never restart SC in session"). Confirmer 3.7.20 dans meta.json.

### Si Jackson decide deploy en l'etat (option B, NON recommandee)

Documenter explicitement dans CHANGELOG + INCIDENT_LOG :
- F12 long_*_bar / long_*_pattern fournissent un signal DIFFERENT du Python.
- Backtests historiques (parquet v4 Python) ne sont PAS comparables a la
  prod live DMP B3 sur ces 4 features.
- Bot 3 NE doit PAS lire ces 4 features sans relabel "long_up_bar_atr" /
  "long_up_bar_sc" pour distinguer.
- Renommer dans Writer KV : `long_up_bar_atr2`, `long_dn_bar_atr2`,
  `long_dn_up_pattern_2bar`, `long_up_dn_pattern_2bar` pour signaler la
  divergence semantique au downstream.

---

## Verifications post-deploy J+1 obligatoires

Si on deploye apres fix BUG #1-3 :

1. **F22 sanity** (sur premier JSONL B3 RTH NQ + ES) :
   ```bash
   python -X utf8 tools/test_parity_B3.py --sym NQ --date YYYYMMDD
   ```
   - pct_in_range : ∈ [0, 100] sur 100% des bars valides
   - premium_zone + discount_zone = 1 toujours (mirror strict)
   - position_in_range : ∈ [0, 1] sur 100% des bars valides
   - Compter mirror violations (premium+discount != 1 quand pct != 50) : doit etre 0.

2. **F12 fire rates** (apres fix) : doivent matcher Python a +- 2pp :
   ```bash
   grep -c '"long_up_bar":1' DATA/NQ/YYYYMMDD_NQ.jsonl
   # Doit etre ~28% des bars (390/1380), pas 0.22%.
   ```

3. **F8 news firing** :
   - is_news_715 / is_news_930 : EXACTEMENT 1 bar/jour fire = 1 (verifier RTH 7h15 ET et 9h30 ET match).
   - within_news_HHMM_5m : 5 bars consecutives fire = 1.
   - mins_since_news < 7h15 ET (avant 1ere news) : verifier `null` (pas -1).
   - mins_to_next_news > 9h30 ET (apres derniere news) : verifier `null`.

4. **F9 is_roll_day** :
   - Sur jour normal (hors trimestre rollover) : 0 sur 100% des bars.
   - **Test obligatoire** : Jackson edit chart pour passer NQ -> ES sur SC. Verifier
     que is_roll_day reste **0** apres switch (manual_switch protection root code).
     Si flag = 1, BUG critique manual_switch detection casse.

5. **schema_version dans JSONL meta** : verifier `"schema_version": "3.7.20"` et
   `"n_columns": 376` dans `YYYYMMDD_NQ.meta.json`.

6. **PersistVars conflict check** :
   ```cpp
   // Confirmer aucun autre helper utilise indices 205-210
   grep -n "GetPersistentFloat(2[0-1][0-9])" CPP/MIA_REFACTORED/DUMPER/*.h
   ```

---

## Resume executive

| Critere | Statut |
|---|---|
| Code C++ compile et n_columns coherent | ✅ |
| F22 (4 features) : formules + sanity OK | ✅ GO |
| F8 (14 features) : formules + sentinelles DMP_INVALID OK | ✅ GO |
| F9 (1 feature) : manual_switch protection OK | ✅ GO |
| F12 (10 features) : 5/10 GO, 4/10 divergence semantique majeure, 1/10 mineure | ❌ NOGO |
| Commentaires source fiables | ❌ COMMENT_FALSE |
| Test parity capture la divergence | ❌ Pas de check fire-rate vs Python |

**Verdict global : NOGO** sur F12. Fix obligatoire BUG #1-3 + #4 commentaires.
F22, F8, F9 sont eligibles a deploy partiel si refactor F12 prend > 2 jours
(decomposition par famille acceptable, schema 3.7.20a a 3.7.20b par exemple).

Cf. categorie incident `COMMENT_FALSE` (pattern 11 V1 — audit superficiel) — a
documenter dans INCIDENT_LOG.

---

*Generated by quality-validator review #2, 2026-06-07. Inputs : code C++ B3 (4 NEW
headers + Reader/Transform/Writer/Config patches), Python live_enriched 6 jours
(5 NQ + 5 ES), sanity script 100% bars valides F22 (mirror_viol=0/6147 total).*
