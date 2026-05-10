# Audit Qualite Datasets ES + MGC v5e — 11/05/2026

**Source** : quality-auditor agent (background dispatch 10/05 soir)
**Datasets** :
- `DATA/DATASETS/ES_dataset_v5e_clean.parquet` (357 826 bars × 469 cols)
- `DATA/DATASETS/MGC_dataset_v5e_clean.parquet` (336 533 bars × 399 cols)

---

## Verdict global

| Dataset | Standalone | Joint (ES+MGC) |
|---|---|---|
| ES | **RESERVES** (1 outlier `n_big_t1`) | **BLOQUE** (61 prix absolus) |
| MGC | **BLOQUE** (1 corruption + 15 dead) | **BLOQUE** (idem) |

---

## Bloquants critiques (action immediate)

### 1. `vwap_d_cross_up` CORRUPTION MGC

- ES : mean=1.7% (taux fire normal cross VWAP)
- MGC : mean=55.5% (32x trop fort) — **bug calcul**
- Cause probable : logique cross VWAP non adaptee aux sessions COMEX gold (timing different)
- Action : DROP definitif MGC OU debugger logique cross dans `phase_b_plus_engine.py` (a investiguer)

### 2. 15 features mortes MGC (std=0)

| Feature | Status |
|---|---|
| `n_edge_buy_active`, `n_edge_sell_active` | std=0 MGC (vs ES mean=8.4/8.9) — edge zones non calculees Gold |
| `bar_edge_buy_fire`, `bar_edge_buy_zone_size` | std=0 MGC — pas implementees |
| `bar_edge_sell_fire`, `bar_edge_sell_zone_size` | std=0 MGC — pas implementees |
| `is_mq_filled`, `bar_no_trade` | std=0 MGC |
| `n_big_t4`, `n_big_buy_t4`, `n_big_sell_t4` | std=0 MGC ET ES — seuil T4 jamais trigger |
| `n_big_ask_v2_t3`, `n_big_bid_v2_t3`, `n_big_ask_v2_t4`, `n_big_bid_v2_t4` | std=0 MGC ET ES |

Action : DROP des 2 datasets (ne pas conserver dead features inutiles).

### 3. `n_big_t1` ES OUTLIER

- max=181, p99=1 → ratio max/p99 = 181x (regle outlier explosion violee)
- Action : CLIP a p99=1 (winsorisation)
- Probable burst cluster count sur 1 bar isole

### 4. `n_big_t1` MGC CALIBRATION CASSEE

- MGC mean=0.45 (45% des bars trigger T1)
- ES mean=0.035 (3.5% des bars trigger T1)
- Ratio 12.7x — **seuil T1 mal calibre pour Gold**
- Action options :
  - (a) Recalibrer T1 MGC dans `phase_b_plus_plus_engine.py:BIG_ORDERS_TIERS_NEW["MGC"]` (sur seuil 10 → 30+ ?)
  - (b) Garder T1 actuel mais ajouter `n_big_t1` a `NATURALLY_DIFFERENT` (utile standalone, leak joint)

---

## Bloquants joint training (ES + MGC dans meme modele)

### 61 colonnes prix absolus bruts

ES ~6500, MGC ~4085 ($/oz) — unites differentes. Modele joint apprendrait instantanement l'instrument.

Liste complete (61 cols) :
```
vwap_d, vwap_d_sd1d/sd1u/sd2d/sd2u/sd3d/sd3u, vwap_m_*, vwap_w_*, pvwap,
pvwap_sd1d/sd1u, cur_vpoc, cur_vah, cur_val, cur_pdh, cur_pdl, pdh, pdl,
prev_vah, prev_val, prev_vpoc, ib_high, ib_low, sess_high, sess_low,
ovn_high, ovn_low, cash_high, cash_low, us_high, us_low, london_*, asia_*,
after_*, ny_open, open_830_et, open_930_et, open_cash, price_1030,
avg_price, _last_swing_high_price, _last_swing_low_price
```

Action joint training : **DROP obligatoire** OU remplacer par versions `_atr` / `_pct`.

Action standalone training : ces colonnes sont utilisables comme references internes (toutes valeurs dans meme echelle).

---

## Faux positifs validator (NE PAS bloquer)

Le validator compare ES vs NQ (calibrage ES/NQ). Pour ES vs MGC (actifs differents), ~80 des 174 flags sont des faux positifs de contexte.

### CONSTANT legitimes (event-based par design)
- `rvol_buy/sell/extreme` (1-3% fire rate)
- `long_up_bar`, `long_dn_bar` (4%)
- `regime_actionable` ES 2.7% / MGC 5.6%
- `is_new_sess_high/low`, `liquidity_sweep_*`
- `vwap_d_sd2_above/below`, `equal_highs/lows_detected`
- `ovn_broken_dn`, `is_news_*`, `within_news_*` (1 bar/day = 0.2%)
- `bn_absorb_*`, `bn_trapped_*`, `cluster_at_high/low`

### INSTRUMENT legitimes (scale naturel ES vs Gold)
- `bars_since_last_spike` ES 336 vs MGC 95 — COMEX plus actif
- `n_color_*_zones_active`, `n_trapped_*_zones_active`
- `cur_va_n_buckets` — granularite tick differente

### INSTRUMENT a EXEMPTER (training joint si besoin)
- `atr_14m_pct` ES 2.7% vs MGC 5.4% — Gold plus volatile en % → exempt
- `ctx_ib_extension_ratio` ES 0.66 vs MGC 0.34 — session COMEX 5h vs NYSE 6.5h → exempt
- `dist_color_*_nearest_pct` ES 0 vs MGC 0.84 ATR → exempt
- `n_big_buy/sell_t1` ES 0.04 vs MGC 0.45 → critique joint training, ok standalone

---

## Plan de fix (priorise)

### Apres rebuild regime z-score (en cours, ~2h compute VPS)

**Etape 1 — Post-process drop + clip (~15 min, no code change)**

```python
# Dans concat_es_dataset.py / concat_mgc_dataset.py apres concat :

# DROP 15 features mortes MGC
DEAD_FEATURES_MGC = [
    "n_edge_buy_active", "n_edge_sell_active",
    "bar_edge_buy_fire", "bar_edge_buy_zone_size",
    "bar_edge_sell_fire", "bar_edge_sell_zone_size",
    "is_mq_filled", "bar_no_trade",
    "n_big_t4", "n_big_buy_t4", "n_big_sell_t4",
    "n_big_ask_v2_t3", "n_big_bid_v2_t3",
    "n_big_ask_v2_t4", "n_big_bid_v2_t4",
]
big = big.drop(columns=[c for c in DEAD_FEATURES_MGC if c in big.columns], errors="ignore")

# DROP vwap_d_cross_up MGC (corruption 55.5%)
# A faire UNIQUEMENT pour MGC, garder pour ES
if symbol == "MGC":
    big = big.drop(columns=["vwap_d_cross_up"], errors="ignore")

# CLIP n_big_t1 ES outlier
if symbol == "ES":
    p99 = big["n_big_t1"].quantile(0.99)
    big["n_big_t1"] = big["n_big_t1"].clip(upper=p99)
```

**Etape 2 — Investigation `vwap_d_cross_up` MGC bug calcul** (a planifier, ~1-2h)

Localiser logique dans `phase_b_plus_engine.py`, identifier pourquoi cross fire 55% sur MGC. Probable :
- timing session COMEX 08:30 ET vs NYSE 09:30 ET
- VWAP daily reset different sur Gold
- Threshold cross trop sensible avec tick 0.10

**Etape 3 — Recalibration `n_big_t1` MGC** (decision : (a) ou (b))

Si (a) recalibrer seuil T1 : modif `phase_b_plus_plus_engine.py:BIG_ORDERS_TIERS_NEW`, rebuild MGC necessaire (1h)
Si (b) marquer naturally_different : pas de rebuild, juste ajouter a `quality_validator.py:NATURALLY_DIFFERENT`

**Etape 4 — Drop prix absolus pour joint training** (si applicable)

Si Phase 2 backtests utilise modele joint ES+MGC : DROP 61 cols dans dataset_builder.
Si backtests standalone (1 modele par instrument) : pas necessaire.

---

## Impact estime

| Dataset | Avant | Apres nettoyage |
|---|---|---|
| ES totales | 469 | ~469 (4 dead communes drop, 1 clip) |
| ES ML-safe standalone | ~420 | ~416 |
| MGC totales | 399 | ~384 (16 drops MGC) |
| MGC ML-safe standalone | ~340 | ~368 |
| Cols communes ML-safe (joint) | ~310 | ~249 (apres drop 61 prix absolus) |

---

## Decisions ouvertes Jackson

1. **`vwap_d_cross_up` MGC** : DROP definitif OU investiguer bug calcul (1-2h dev) ?
2. **`n_big_t1` MGC** : option (a) recalibrer seuil OU (b) mark naturally_different ?
3. **Joint training ES+MGC** : on prevoit modele joint OU standalone par instrument ?
4. **Backfill `vwap_d_cross_up`** : si on debug, faut rebuild — combien de mois ?

---

## Statut

- **Rebuild regime z-score** en cours sur VPS (~2h compute) — background task `beakgyfg5`
- **Quality-auditor** complet (rapport ci-dessus)
- **Next** : post-process drop + clip dans concat scripts apres rebuild fini
