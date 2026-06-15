# Analyse invalidation par scénario — stop structurel

**Date** : 2026-06-15
**Contexte** : fix unité ATR (daily ticks → intraday points) a révélé que le stop
`0.8 × ATR` n'a aucun sens d'horizon. Le stop doit être placé au **niveau dont le
franchissement DÉTRUIT la prémisse du trade** (invalidation structurelle), pas à un
multiple d'ATR arbitraire.

**Principe** : SI stop touché → le scénario est faux → on sort. Le stop EST la
définition empirique de "j'ai eu tort".

**Mécanisme code** : `_make_setup_long/short(..., stop_level=X)`.
- Si `stop_level` fourni : `stop = stop_level ∓ STOP_BUFFER_ATR_FRAC(0.25) × atr_intraday`
- Sinon : fallback ATR (scalp 0.3 / swing 0.8) — légitime UNIQUEMENT pour les scalps
  à horizon court (target < 1 ATR).

`atr` dans ctx = ATR intraday en POINTS (`atr_14m_ticks × tick_size`), ~12 pts NQ.

---

## Classification

| Famille | Définition | Stop |
|---|---|---|
| **A — Fade/pullback à un niveau** | entry = le niveau (support/résistance) | cassure de CE niveau |
| **B — Momentum/reversal** | entry = close, invalidation à un niveau distinct | au-delà du niveau d'invalidation |
| **Scalp court** | target < 1 ATR + stop 0.3 ATR | ATR scalp (horizon cohérent, PAS de changement) |

---

## Mapping par builder (12 restants, ib_break déjà fait)

### Famille A — fades (stop = niveau d'entrée)

| # | Builder | Entry | Invalidation logique | stop_level | Dispo ctx |
|---|---|---|---|---|---|
| 1 | `bullish_continuation` LONG | `near_sup` | cassure support = fin du pullback, breakdown | `near_sup.price` | ✅ |
| 2 | `bearish_rejection` SHORT | `major_res` | cassure résistance = rejet échoué (Wyckoff test raté) | `major_res.price` | ✅ |
| 3 | `range_bound_long_fade` | `near_sup` | cassure support = sortie range par le bas | `near_sup.price` | ✅ |
| 4 | `range_bound_short_fade` | `near_res` | cassure résistance = sortie range par le haut | `near_res.price` | ✅ |

**Note famille A** : entry collé au niveau → risk = buffer seul. RR élevé est NORMAL
pour un fade (on risque peu au niveau, on vise loin) ; c'est le WR qui est plus bas.
**Question market-analyst** : buffer 0.25 ATR (~3 pts NQ) suffisant pour distinguer
"mèche de test" de "vraie cassure" ? Ou 0.4-0.5 ATR ?

### Famille B — reversal/momentum (stop = niveau distinct)

| # | Builder | Entry | Invalidation logique (canon) | stop_level | Dispo ctx |
|---|---|---|---|---|---|
| 5 | `judas_reversal` LONG/SHORT | close | retour au-delà de l'**extrême du judas swing** (le faux move) | extrême judas | ❌ **à enrichir** |
| 6 | `failed_breakout` Spring/UTAD | close | re-cassure de l'**extrême du sweep** (Wyckoff : sous spring low / sur UTAD high) | bar low/high courant (sweep this bar) | ❌ **à enrichir** |
| 9 | `bn_fired_confluence` | close | cassure du **niveau de confluence** qui justifie le BN (souverain Jackson) | `confluence_level.price` | ✅ |
| 10 | `open_type_driven` Open Drive | close | retour à l'**open price** (Dalton : OD invalidé si retour à l'open) | open price | ❌ **à enrichir** |
| 11 | `vwap_sd_touch_reversal` (SD2/SD3) | close | **acceptance au-delà de la bande SD** (l'exhaustion stat a échoué) | `sd_level` touchée ± buffer | ✅ |
| 12 | `holy_grail` Raschke | close | cassure de la **VWAP day** (proxy 20-EMA — Raschke : stop de l'autre côté de la MA) | `vwap_d` | ✅ |

### Scalps — PAS de stop structurel (horizon déjà cohérent)

| # | Builder | Raison |
|---|---|---|
| 7 | `fvg_magnet` | target = close + fvg_dist (<1 ATR), stop scalp 0.3 ATR → RR ~2-3 cohérent |
| 8 | `single_print_magnet` | target = close + dist (\|dist\|<1.5 ATR), stop scalp 0.3 → RR <5 acceptable |

**Réserve** : `vwap_sd2` est marqué `scalp` mais son target = `vwap_d` (loin, ~2 SD).
Incohérence horizon → le traiter comme Famille B (stop = bande SD2), pas scalp.

---

## Enrichissements NarrativeContext requis (3 niveaux manquants)

`NarrativeContext` expose les **bools** sweep/judas mais pas les **prix** :
- `sweep_low_this_bar` / `sweep_high_this_bar` (bool) → manque le prix de l'extrême
- `judas_swing_active` / `judas_swing_direction` → manque l'extrême du swing
- `open_relation` / `open_direction` → manque le **prix d'open cash**

**À ajouter dans `build_narrative_context` / `_extract_*`** :
1. `sweep_extreme_price` : bar low (spring) / bar high (UTAD) de la barre courante
   (le sweep est `this_bar`, donc = bar["low"]/bar["high"])
2. `judas_extreme_price` : high/low de la fenêtre London first hour (champ source à
   identifier — `london_high`/`london_low` ?)
3. `open_price_cash` : `bar["open_cash"]` ou équivalent (à identifier)

**Si un niveau reste indisponible** → fallback documenté : proxy `near_sup`/`near_res`
opposé, OU garder fallback ATR pour CE builder (avec commentaire explicite).

---

## Questions ouvertes pour market-analyst

1. **Famille A buffer** : 0.25 vs 0.4-0.5 ATR sous le niveau ? (mèche vs cassure réelle)
2. **Judas** : l'invalidation est-elle l'extrême du judas, ou le retour à `london_open` ?
3. **Spring/UTAD** : stop sous le low de la barre de sweep, ou sous le low de la range
   balayée (plus large) ? Wyckoff canon.
4. **Open Drive** : open price exact, ou retour sous VWAP/dans IB acceptable comme proxy ?
5. **VWAP SD touch** : stop à la bande touchée (serré, ~touch) ou à la bande SUIVANTE
   (SD3 si on short SD2) pour laisser respirer ?
6. **Holy Grail** : VWAP day suffit, ou faut-il le swing low du pullback (Raschke
   original = stop sous le pullback low) ?
