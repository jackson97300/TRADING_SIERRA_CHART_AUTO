# Design — Entrées de qualité, forte conviction (retest + confirmation)

**Date** : 2026-06-15
**Philosophie (Jackson)** : *attendre le bon moment, confirmation, pas de précipitation,
signaux de qualité à forte conviction*. Aligné Mark Douglas (consistency > intensity),
règle souveraine BN (« aucune zone ne se trade seule = confluence + niveau solide »),
cible **3-5 trades/jour** (max_trades 5).

**Problème constaté empiriquement (15/06)** : le moteur sort 68 signaux/jour en
entrant **au close** (chase). Le test chase vs retest montre que l'entrée sur retest
~triple l'EV (BN +2.7→+7.6) et coupe les trades de moitié.

**Châssis existant** : `scenario_tracker` a déjà le lifecycle
`PENDING → ACTIVE_ENTRY_ZONE → TRIGGERED` (attendre → retest → confirmation). MAIS :
- `entry_zone` est placée autour du **close** (chase), pas du niveau → à corriger
- les `conditions_validation` sont du **texte non évaluable** → confirmation factice
- aucun **filtre de conviction** → tous les scénarios passent

**Champs de confirmation évaluables** (`scenario_conditions.KNOWN_FIELDS`) : delta_bar,
finish_strength, cvd_session, bn_absorb_bid/ask, bn_score_raw, bn_long_up/dn, delta_divergence,
sweep_*_this_bar, ib_broken_*, bool_above_vwap_d, vwap_triple_align, trend_day_probability...

---

## Les 4 pièces par scénario

| # | Pièce | Rôle |
|---|---|---|
| 1 | **entry_zone** (zone de retest) | où le prix doit revenir = autour du niveau déclencheur (pas le close) |
| 2 | **confirmation** (conditions DSL évaluables) | au retest, l'order-flow doit confirmer (delta, rejet, absorption) — pas juste toucher |
| 3 | **stop recouplé** | si l'entry passe au niveau de retest, le RR change → stop re-dérivé |
| 4 | **conviction** (filtre) | n'émettre/tracker que les setups forts (confluence + alignement + score) |

---

## Design par scénario

### Famille A — fades (entrent DÉJÀ au niveau, manque la confirmation réelle)

| Scénario | entry_zone | Confirmation (DSL) | Stop (déjà câblé) | Conviction |
|---|---|---|---|---|
| bullish_continuation | near_sup ± buffer | `delta_bar > 0` ET `finish_strength > 0` | swing_low | macro BULL + profile P + confluence≥2 |
| bearish_rejection | major_res ± buffer | `delta_bar < 0` ET `finish_strength < 0` ET `bn_absorb_ask > 0` | major_res | **confluence≥3** + `sweep_high_this_bar` |
| range_long_fade | near_sup ± buffer | `delta_bar > 0` ET `bn_absorb_bid > 0` | near_sup | day_type range + confluence≥2 |
| range_short_fade | near_res ± buffer | `delta_bar < 0` ET `bn_absorb_ask > 0` | near_res | day_type range + confluence≥2 |

### Famille B — chasers (entry passe de close → niveau de retest, stop recouplé)

| Scénario | entry_zone (retest) | Confirmation (DSL) | Stop RECOUPLÉ | Conviction |
|---|---|---|---|---|
| IB Break | **ib_high** (long) / ib_low (short) ± buffer | `delta_bar > 0` ET `ib_broken_up` tient | **swing_low** (PAS ib_high = entry) | ib_is_narrow + bias aligné + `cvd_session` fort |
| spring/UTAD | retour vers extrême sweep | `delta_bar > 0` (spring) + close>entry | bar_low/high (sweep) | `bn_absorb_bid` + macro aligné |
| bn_fired | **confluence_level** ± buffer | `bn_absorb_bid/ask > 0` ET `delta_bar` aligné | sup_lvl (bon côté) | **confluence≥2 + bn_score_raw fort** |
| open_drive | **PAS de retest** (OD ne retrace pas, Dalton) garde close | `delta_bar` aligné + pas de retour open | open_cash | `open_bias_conf ≥ 0.7` + `trend_day_probability > 0.6` |
| vwap_sd touch | bande SD ± buffer (au touch) | `delta_divergence` opposé + reversal wick | bande SD | SD3 > SD2 + divergence présente |
| holy_grail | zone autour vwap_d (pullback) | reversal bar + `delta_bar` aligné | swing_low/high | `trend_day_probability ≥ 0.7` + `vwap_triple_align` |
| judas | (bloqué pipeline — London null US) | — | fallback ATR | judas_swing_active confirmé |

**Note couplage entry/stop (IB Break)** : aujourd'hui entry=close, stop=ib_high. Si
entry passe à ib_high (retest), le stop ib_high devient = entry → impossible. Le stop
doit descendre au **swing_low** (ou ib_low). C'est le recouplage central de ce chantier.

---

## Le filtre de conviction (pièce 4 — ce qui fait 68 → 3-5 trades)

Un setup n'est TRACKÉ (PENDING) que si **TOUS** ces critères sont réunis :

1. **Niveau solide** : `confluence_count ≥ 2` sur le niveau d'entrée (règle souveraine BN)
2. **Alignement** : direction cohérente avec macro_bias (pas de contre-tendance, SAUF
   exhaustion forte = vwap_sd3 + divergence)
3. **Score** : `heuristic_score ≥ seuil` (à calibrer, ~60 indicatif)
4. **Confirmation order-flow obligatoire** au retest (pièce 2) — sinon EXPIRED sans trade

Ces 4 filtres sont cumulatifs (AND). C'est volontairement restrictif (Douglas : rater un
trade > prendre un mauvais). Calibration du seuil en observe-only.

**Anti-PATTERN_11** : ces critères sont des FILTRES de qualité documentés, pas un score
composite hardcodé qui remplace le ML. Ils réduisent le bruit ; la sélection fine
(lesquels gardent un edge) reste mesurée en observe-only + DSR.

---

## VERDICT market-analyst (15/06) + verification empirique Claude

**Design conceptuel : VALIDÉ** (retest IB=Dalton, confluence=BN Jackson, exception
open_drive=correct, pullback VWAP=Raschke, mean reversion SD=Steenbarger). Verdict
global RESERVES car implémentation en retard. 3 risques :

1. **Confirmation décorative (BLOQUANT, prérequis #1)** : le mécanisme tracker
   (parse à la création ligne 663 → evaluate par barre) FONCTIONNE. Vérifié empirique :
   `bn_absorb_bid > 0`, `delta_bar > 0`, `ib_broken_up == 1` → parsent et évaluent True.
   MAIS les conditions des builders sont du **texte descriptif** (`"Rebond confirme sur
   support (close > entry + 0.2 ATR)"`, `"BN absorb_bid > 0 OU bn_long_up = 1"`) →
   `_unparsable` → toujours False → confirmation jamais atteinte.
   FIX = réécrire conditions_validation/invalidation en **DSL propre** (champ_simple
   minuscule + opérateur + nombre). Champs dispo verifiés dans barre SIERRA (PAS
   databento) : delta_bar, finish_strength, cvd_session, bn_absorb_bid/ask, bn_score_raw,
   bn_long_up/dn, sweep_high/low_this_bar, ib_broken_up/down, bool_above_vwap_d,
   vwap_triple_align, delta_div_strength. (NB market-analyst a checké le mauvais fichier
   databento → ses "fields absents" sont en fait présents côté Sierra.)

2. **Famille B pas migrée** : IB Break / bn_fired / spring entrent encore au close.
   Migration close→retest à faire (entry_zone + stop recouplé d'un bloc).

3. **Recouplage IB Break** : entry→ib_high impose stop→**ib_low** (PAS ib_high=entry,
   PAS swing_low mal défini post-break). bearish_rejection buffer 0.4-0.5 (pas 0.25).

Corrections market-analyst : entry_zone famille B 0.20-0.25 ATR (vs A 0.10-0.15) ;
fenêtre retest MAX_BARS_TO_TOUCH_ZONE ~20 barres ; contre-tendance bearish_rejection
GARDÉE mais exhaustion obligatoire (delta_div_strength/finish_strength) + ne pas exiger
alignement macro + logger macro_bias pour calibration ; confirmation = 2 signaux
order-flow non redondants.

## Ordre de travail (revise)

```
1. Reparer confirmation : reecrire conditions en DSL propre (prerequis bloquant)
2. Migrer entrees famille B (close -> retest) + recoupler stops (IB->ib_low)
3. entry_zone width par famille + MAX_BARS_TO_TOUCH_ZONE ~20
4. Filtre conviction (confluence>=2 + alignement + score, hors bearish_rejection exhaustion)
5. pytest + code-reviewer + commit
6. Observe-only jours haussiers ET baissiers + DSR
```

## Questions pour market-analyst (RESOLUES ci-dessus)

1. **entry_zone width** : buffer de retest = quelle fraction d'ATR autour du niveau ?
   (assez large pour être touché, assez serré pour rester "au niveau")
2. **IB Break stop recouplé** : swing_low ou ib_low ? (swing_low plus serré, ib_low =
   invalidation complète du break)
3. **open_drive** : confirmer qu'on NE met PAS de retest (OD = momentum, ne retrace pas) ?
4. **Confirmation minimale** : 1 condition order-flow suffit, ou exiger 2 (delta ET
   rejet) pour la "forte conviction" ?
5. **Fenêtre de retest** : combien de barres max en PENDING avant EXPIRED (le prix doit
   revenir au niveau dans X barres sinon on abandonne) ?
6. **Contre-tendance** : bearish_rejection en marché haussier = à bloquer (conviction)
   ou à garder si confluence≥3 + exhaustion ?
