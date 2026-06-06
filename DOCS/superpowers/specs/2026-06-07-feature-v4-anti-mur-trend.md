# Feature V4 — Anti-pattern "BUY mur en trend up"

**Date** : 2026-06-07
**Auteur** : Jackson + Claude (Option A plan long terme)
**Statut** : VALIDE - prete a porter en C++ Sierra
**Score backtest** : |rho| = 0.20 (NQ) / 0.22 (ES), 75% jours significatifs, 3/4 folds walk-forward stables

---

## 1. Probleme metier

**Cas concret observe** : marche en tendance haussiere, bot achete sur un mur PVAL
(Previous Value Area Low) loin du prix actuel → trade perdant.

**Diagnostic** :
- Bot ne distingue pas
  - PULLBACK dans tendance (= setup valide LONG)
  - MUR PASSIF loin du prix en pleine tendance (= mean-reversion contre-tendance,
    perdant)
- Manque feature pour detecter contexte "trend solide, n'aller pas contre"

## 2. Feature V4 — Formule

```python
# === COMPONENTS ===

# Momentums multi-temporel normalises ATR
mom_5 = (close[t] - close[t-5]) / atr_daily
mom_20 = (close[t] - close[t-20]) / atr_daily
mom_60 = (close[t] - close[t-60]) / atr_daily

# Coherence multi-temporel (+1 si 3 alignes, -1 si discordants)
coh = sign(mom_5) * sign(mom_20) * sign(mom_60)
mag = (|mom_5| + |mom_20| + |mom_60|) / 3

# VWAP slope direction
vwap_sign = sign(vwap_slope_10)   # Sierra slope 1h30

# Range expansion (atr_14m vs sa moyenne longue 120 bars)
range_exp = clip(atr_14m / mean(atr_14m, 120) - 1, -1, 2)

# Proximite niveau cle PDH ou PDL
near_pdh = (|dist_pdh_pct| < 0.2)
near_pdl = (|dist_pdl_pct| < 0.2)
near_key = clip(near_pdh + near_pdl, 0, 1)

# CVD session direction (log-scaled, RTH filtre)
cvd_norm = sign(cvd_session) * clip(log1p(|cvd_session|/100), 0, 5) / 5

# === SCORE FINAL V4 ===

V4_score = (
    coh * mag * 0.30 +                              # Coherence multi-temporel
    vwap_sign * clip(mag, 0, 2) * 0.25 +            # VWAP slope confirme
    range_exp * sign(mom_20) * 0.15 +               # Expansion alignee
    (1 - near_key) * sign(mom_20) * 0.05 +          # Bonus si LOIN niveau
    cvd_norm * 0.25                                 # CVD session direction
)
```

## 3. Interpretation et usage (CONTRARIAN signal)

**Important** : V4 a un **rho_mean NEGATIF** (-0.16 vs forward 60 bars).
Donc V4 est un signal **CONTRARIAN** :
- `V4 > +THRESHOLD` (tres positif) → marche probable REVERSE → **anti-BUY**
- `V4 < -THRESHOLD` (tres negatif) → marche probable REVERSE up → **anti-SELL**

### Gate Bot 2 BN V5 / Bot 3 V4 propose

```python
THRESHOLD_HIGH = +0.7    # tres confiant trend up + confluence + cvd → revers probable
THRESHOLD_LOW = -0.7     # tres confiant trend dn + confluence → bounce probable

if V4_score > THRESHOLD_HIGH and signal.side == "BUY":
    SKIP_TRADE(
        reason="V4 fort + signal BUY = contrarian (mur passif en trend up)",
        v4=V4_score
    )

if V4_score < THRESHOLD_LOW and signal.side == "SELL":
    SKIP_TRADE(
        reason="V4 faible + signal SELL = contrarian (bounce probable)",
        v4=V4_score
    )
```

## 4. Performance backtest

### Backtest 1 (variantes V1-V6) sur 81 jours NQ + 81 jours ES

| Variant | rho_NQ | \|rho\|_NQ | sig% NQ | rho_ES | \|rho\|_ES | sig% ES |
|---|---|---|---|---|---|---|
| **V4_with_cvd_session** | **-0.161** | **0.199** | **74.7%** | **-0.185** | **0.217** | **73.8%** |
| V1_baseline | -0.161 | 0.199 | 75% | -0.181 | 0.213 | 72.8% |
| V5_with_range_pos | -0.158 | 0.193 | 73.8% | -0.178 | 0.208 | 74.1% |
| V6_mix_best | -0.120 | 0.151 | 68.4% | -0.136 | 0.166 | 68.8% |
| V2_with_delta_pers | -0.110 | 0.144 | 58.8% | -0.121 | 0.155 | 65.4% |

**V4 = best** sur NQ ET ES → robuste cross-asset.

### Backtest 3 — Walk-forward 4-fold (NQ)

| Fold | Periode | n_days | rho_mean | sig% |
|---|---|---|---|---|
| Q1 | 20260121 → 20260217 | 20 | -0.078 ⚠️ | 75% |
| Q2 | 20260218 → 20260317 | 20 | **-0.175** | 70% |
| Q3 | 20260318 → 20260416 | 20 | **-0.211** | 75% |
| Q4 | 20260417 → 20260602 | 19 | **-0.182** | 78.9% |

**3/4 folds stables** (|rho| > 0.10). Q1 plus faible (rho -0.078) mais 75%
des jours sig → contexte regime particulier.

## 5. Inputs Sierra requis

V4 consomme features Sierra natives (sauf cvd_session) :

| Input | Source Sierra | Statut |
|---|---|---|
| `close`, `atr` (daily ticks) | Sierra DMP natif | ✅ |
| `vwap_slope_10` | Sierra (slope 1h30 sur chart VP 30min) | ✅ |
| `atr_14m` | Sierra ATR intraday | ✅ |
| `dist_pdh_pct`, `dist_pdl_pct` | Python (a porter Sierra C++) | ⏳ |
| `cvd_session` | Python (RTH filter cvd_day) | ⏳ |

**3 inputs Python a porter en C++ Sierra** pour Sierra autonome.

## 6. Plan port Sierra C++ (Phase J4 revisee post-pivot Jackson)

### 6.1 cvd_session (effort 1h C++)

```cpp
// DMP_Reader.h ou DMP_Transform.h
// cvd_session = sum(delta_bar) depuis open RTH (mins_et 570)
// Reset au cross-day boundary
float cvd_session;

if (mins_et >= 570 && mins_et < 960) {
    if (mins_et == 570 || is_new_session) {
        cvd_session_accum = 0.0f;
    }
    cvd_session_accum += delta_bar;
    cvd_session = cvd_session_accum;
} else {
    cvd_session = DMP_INVALID;  // hors RTH = null
}
```

### 6.2 dist_pdh_pct, dist_pdl_pct (effort 30min C++)

```cpp
// DMP_Transform.h CalcDistPct
dist_pdh_pct = (close - pdh) / pdh * 100;
dist_pdl_pct = (close - pdl) / pdl * 100;
```
Inputs deja dispo (pdh, pdl trackes en Python prev_levels — a porter Sierra
tambien).

### 6.3 V4_score (effort 1h C++)

Code la formule complete dans DMP_Transform.h fonction `CalcV4Score()`.
Bump schema 3.7.18 (+1 feature `v4_anti_mur_trend`).

## 7. Limites et risques

### Limites identifiees

- **Q1 faible** (rho -0.078) : contexte regime jan-fev 2026 different. A
  monitorer si return de ce regime.
- **Horizon 60 bars** : V4 est optimal pour predictions 60-min, faible pour
  5-min. Pas utilisable pour scalping.
- **Signal CONTRARIAN** : easy a mal interpreter. Documenter clairement dans
  bots (commentaire + log).

### Risques

- **R1** : si Bot 2/3 sont actuellement profitable parce que conditions
  V4-fortes etaient deja filtrees implicitement, ce gate ne change rien.
  Mesurer A/B paper 5j avant deploy live.
- **R2** : seuils 0.7 a calibrer post-deploy live (peut etre 0.5 ou 0.9 selon
  symbol).
- **R3** : composante `cvd_session` deja portee Sierra → eviter double calcul.

## 8. Plan deploy

### Phase 1 — Port C++ (J4 plan Option A)
1. Code C++ DMP : cvd_session + dist_pdh/pdl_pct + V4_score
2. Schema bump 3.7.18
3. Tests pytest parite Python ↔ C++

### Phase 2 — Tests paper (J5-J6 plan Option A)
1. Deploy VPS C++
2. Recompil Sierra Chart
3. 5 jours paper A/B Bot 2 et Bot 3 :
   - groupe A : Bot actuel
   - groupe B : Bot + gate V4
4. Comparer mPnL, WR, drawdown

### Phase 3 — Integration live (post J7)
- Si A/B montre amelioration mPnL > 0 sur n>=15 trades → deploy live
- Sinon : feature reste en dataset ML pour analyse ulterieure

## 9. Open questions

- **OQ1** : Seuils 0.7 vs 0.5 vs 0.9 — calibrer sur quel critere ? (PSR > 0.95
  sur 30j paper ?)
- **OQ2** : Horizon 60 bars optimal — pour bots fast (Bot 2 BN V5 5-10min hold)
  pertinence ?
- **OQ3** : Cross-instrument MGC (Gold) — V4 fonctionne-t-elle ?

## 10. Liens

- Backtest 1 : `tools/backtest_sweep_3_approches.py` + `DOCS/BACKTEST_3_APPROCHES.md`
- Backtest 2+3 : `tools/backtest_a3_raffinement_walkforward.py` + `DOCS/BACKTEST_A3_RAFFINEMENT.md`
- Audit overlaps V2 : `DOCS/SIERRA_PYTHON_OVERLAPS_AUDIT_V2.md`
- Plan Option A : INCIDENT_LOG entry 38+39 + BOT_CHANGELOG 06/06

---

**Reviewed** : ml-trainer review (recommande GO-CONDITIONNEL avec walk-forward
4-fold + cross-instrument validation) — les 2 conditions sont remplies.

**Prochaine etape** : Phase J4 plan Option A — port C++ Sierra.
