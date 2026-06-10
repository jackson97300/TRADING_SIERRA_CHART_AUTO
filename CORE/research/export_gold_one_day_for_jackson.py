"""Export 1 journée Gold complète enrichie pour l'agent extérieur.

Mission Jackson (12/05/2026) : agent extérieur (Claude.com / quant) va analyser
1 journée Gold avec TOUTES les features enrichies → proposer des RULES de trading.

Date sélectionnée : 2026-05-08 (vendredi, dernier weekday avec MQ Gold complet
dans le backfill jan-mai 2026).

Output dossier : D:/TRADING_SIERRA_CHART_AUTO/DEMANDE JACKSON/

Fichiers produits :
  1. gold_20260508_full.csv          (toutes features, ouvre Excel)
  2. gold_20260508_full.parquet      (même chose, compact)
  3. gold_20260508_menthorq_levels.json  (niveaux MQ du jour pour contexte)
  4. README_GOLD_FEATURES.md         (doc des features par catégorie + objectif)
"""
import json
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "CORE"))

import pandas as pd

INPUT = ROOT / "DATA" / "DATASETS" / "MGC_dataset_v5e_mq_enriched.parquet"
OUT_DIR = ROOT / "DEMANDE JACKSON"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TARGET_DATE = date(2026, 4, 1)  # mercredi, intersection bars MGC + MQ Gold backfill (01/04 dernier MQ dispo avant gap)

print(f"=== Export Gold 1 day pour agent extérieur ===\n")
print(f"  Source : {INPUT}")
print(f"  Output : {OUT_DIR}")
print(f"  Date cible : {TARGET_DATE} (vendredi)")

# Load + filter
df = pd.read_parquet(INPUT)
print(f"\n  Loaded {df.shape}")

ts = pd.to_datetime(df["ts_event"], errors="coerce")
mask = ts.dt.date == TARGET_DATE
df_day = df[mask].copy().reset_index(drop=True)
print(f"  Filtered to {TARGET_DATE} : {df_day.shape}")

# Tri par ts_event
df_day = df_day.sort_values("ts_event").reset_index(drop=True)

# Sessions visibles
sessions = {}
for s in ["is_in_asia", "is_in_london", "is_in_us_cash", "is_in_us_after"]:
    if s in df_day.columns:
        sessions[s] = int(df_day[s].sum())
print(f"  Sessions distribution : {sessions}")

# Export CSV + parquet
csv_out = OUT_DIR / f"gold_{TARGET_DATE.strftime('%Y%m%d')}_full.csv"
parquet_out = OUT_DIR / f"gold_{TARGET_DATE.strftime('%Y%m%d')}_full.parquet"
df_day.to_csv(csv_out, index=False)
df_day.to_parquet(parquet_out, index=False)
print(f"\n  CSV     : {csv_out} ({csv_out.stat().st_size / 1024:.1f} KB)")
print(f"  Parquet : {parquet_out} ({parquet_out.stat().st_size / 1024:.1f} KB)")

# Copy MenthorQ levels JSON
mq_src = ROOT / "DATA" / "MENTHORQ" / "gold_history" / f"{TARGET_DATE.strftime('%Y%m%d')}_gold_levels.json"
mq_dst = OUT_DIR / f"gold_{TARGET_DATE.strftime('%Y%m%d')}_menthorq_levels.json"
if mq_src.exists():
    shutil.copy(mq_src, mq_dst)
    print(f"  MQ JSON : {mq_dst}")
else:
    print(f"  [WARN] MQ JSON source absent : {mq_src}")

# Inventaire colonnes par catégorie
print(f"\n  Inventaire features :")
cols = df_day.columns.tolist()
categories = {
    "OHLCV brut": [c for c in cols if c in ("ts_event", "open", "high", "low", "close", "volume")],
    "ATR / Volatility": [c for c in cols if "atr" in c.lower() or "vol" in c.lower()][:15],
    "Sessions": [c for c in cols if "session" in c.lower() or "is_in_" in c.lower()][:10],
    "VWAP": [c for c in cols if "vwap" in c.lower()][:15],
    "Volume Profile / VPOC": [c for c in cols if "vpoc" in c.lower() or "vah" in c.lower() or "val" in c.lower()][:10],
    "IB (Initial Balance)": [c for c in cols if "ib_" in c.lower()][:10],
    "Distances dist_*": [c for c in cols if c.startswith("dist_")][:30],
    "MQ Gold (Phase D)": [c for c in cols if c.startswith(("dist_mq_", "dist_blind_", "dist_gex_", "dist_1d_", "gex_cluster", "bool_above_mq", "bool_gex"))][:20],
    "Intermarket (Phase D)": [c for c in cols if c.startswith("im_") or c in ("gold_silver_ratio", "gold_silver_ratio_zscore_60d", "copper_gold_ratio", "copper_gold_ratio_momentum_30", "oil_gold_ratio_zscore_60d")][:15],
    "Gold session (Phase D)": [c for c in cols if "mgc_" in c or "london_fix" in c or "asia_breakout" in c][:10],
    "Swings / Levels structurels": [c for c in cols if "swing" in c.lower() or "1d_" in c.lower() or "single_print" in c.lower()][:15],
    "News flags": [c for c in cols if "news" in c.lower() or "within_news" in c][:10],
    "Bias / Delta": [c for c in cols if "bias" in c.lower() or "delta" in c.lower() or "cvd" in c.lower()][:15],
    "Open type / Day type": [c for c in cols if "open_type" in c or "day_type" in c or "profile_shape" in c][:5],
}
for cat, cs in categories.items():
    print(f"    {cat:30s} : {len(cs)} cols (sample : {cs[:5]})")

# README — construction en 2 étapes pour éviter conflit f-string + JSON braces
sessions_str = f"Asia={sessions.get('is_in_asia',0)} bars, London={sessions.get('is_in_london',0)}, US_Cash={sessions.get('is_in_us_cash',0)}, US_After={sessions.get('is_in_us_after',0)}"
target_compact = TARGET_DATE.strftime('%Y%m%d')

readme = f"""# Demande Jackson — 1 journée Gold enrichie pour analyse agent extérieur

**Date** : 2026-05-12 (export généré)
**Date data** : {TARGET_DATE} (vendredi)
**Symbole** : MGC (Micro Gold futures Jun 2026)

## Fichiers

| Fichier | Description |
|---|---|
| `gold_{TARGET_DATE.strftime('%Y%m%d')}_full.csv` | Toutes les features de la journée (Excel-readable) |
| `gold_{TARGET_DATE.strftime('%Y%m%d')}_full.parquet` | Même chose, format compact |
| `gold_{TARGET_DATE.strftime('%Y%m%d')}_menthorq_levels.json` | Niveaux MenthorQ Gold du jour (Call/Put/HVL/BL/0DTE) |

## Statistiques journée

- **Total bars** : {len(df_day)} (1-min bars)
- **Open** : {df_day['open'].iloc[0]:.2f}
- **High** : {df_day['high'].max():.2f}
- **Low** : {df_day['low'].min():.2f}
- **Close** : {df_day['close'].iloc[-1]:.2f}
- **Volume total** : {int(df_day['volume'].sum()):,}
- **ATR per-bar median** : {df_day['atr'].median():.1f} ticks
- **Sessions** : Asia={sessions.get('is_in_asia',0)} bars, London={sessions.get('is_in_london',0)}, US_Cash={sessions.get('is_in_us_cash',0)}, US_After={sessions.get('is_in_us_after',0)}

## Inventaire features ({len(cols)} colonnes au total)

### Catégories principales

| Catégorie | Nb features | Exemples |
|---|---|---|
"""
for cat, cs in categories.items():
    if cs:
        readme += f"| {cat} | {len(cs)} | `{cs[0]}`, `{cs[1] if len(cs) > 1 else ''}` |\n"
readme += f"""

## Niveaux MenthorQ du jour ({TARGET_DATE})

Lire `gold_{TARGET_DATE.strftime('%Y%m%d')}_menthorq_levels.json` pour les key_levels parsés.

Notamment :
- `call_resistance` : niveau de résistance principal (gamma call concentré)
- `put_support` : niveau de support principal (gamma put concentré)
- `hvl` : Heightened Volatility Level (pivot intraday majeur)
- `1d_max` / `1d_min` : range journalier prédit par MenthorQ
- `call_resistance_0dte`, `put_support_0dte`, `hvl_0dte`, `gamma_wall_0dte` : niveaux options 0DTE (très structurants)
- `bl_levels[10]` : 10 Blind Spots (zones gamma vides où le prix se déplace vite)

## Features dérivées (calculées sur prix)

- `dist_mq_call`, `dist_mq_put`, `dist_mq_hvl` : distance au niveau MQ en TICKS (tick Gold = 0.10)
- `dist_blind_nearest_up/dn` : distance au Blind Spot le plus proche
- `bool_above_mq_call` : 1 si prix au-dessus de call_resistance
- `bool_gex_flip_zone` : 1 si prix entre call_resistance et put_support (zone gamma neutre)

## MISSION POUR L'AGENT EXTERIEUR

**Objectif** : trouver des **rules de trading Gold** à partir de cette journée + features enrichies.

Type de rules attendues (format similaire Bot 3 ES/NQ) — exemple textuel :
- IF abs(dist_mq_call) < 50 ticks
- AND atr_regime_zscore_60d > 1.5
- AND im_real_yields_proxy < -0.5
- AND bool_above_mq_call == 0
- THEN entry = SHORT
- SL = mq_call + 50 ticks
- TP = mq_hvl (next support)

**Patterns à investiguer** :

1. **Mean reversion sur niveaux MQ** : prix touche mq_call → rebond ?
2. **Breakout 0DTE** : prix casse call_resistance_0dte avec gamma_condition negative → momentum LONG ?
3. **Asia breakout vers London** : asia_breakout_strength élevé → continuation directionnelle ?
4. **DXY divergence** : im_dxy_corr_60d s'éloigne de baseline -0.45 → setup mean rev ?
5. **Real yields extreme** : im_real_yields_proxy z-extreme → reversal Gold ?
6. **Gold/Silver ratio** : gold_silver_ratio_zscore_60d > 2 → mean rev short Gold ?
7. **London Fix vol spike** : london_fix_window_10_30 + atr régime → setup spécifique ?

**Format de retour souhaité** : un fichier `rules_gold.json` avec liste d'objets ayant les champs suivants :
- `name` (string, ID rule)
- `entry_condition` (string, expression Python testable)
- `side` ("LONG" | "SHORT")
- `sl_logic` (string, formule SL en ticks)
- `tp_logic` (string, formule TP en ticks)
- `expected_pf` (float, PF backtesté estimé)
- `notes` (string, raisonnement)

## Contexte business

- **Bot 1 Gold (Sim1)** : ML LightGBM pur, edge validé walk-forward (PF 2.32, DSR 1.0)
- **Bot 3 Gold (Sim3)** : à construire à partir de tes RULES → bot full rules
- **Sim2** : approche niveaux + filtres CTA (en attente backfill CTA historique)

Le **but de Bot 3 RULES** : avoir un système **interprétable** (vs ML black-box du Bot 1).
Sur ES/NQ, Bot 3 = touch d'un niveau Tier 1/2/3 + side rule. À reproduire pour Gold avec **features intermarket + MQ Gold + session-based**.

## Tick / Sizing Gold

- **Tick size MGC** : 0.10 (vs 0.25 ES/NQ)
- **$/tick MGC** : 1.00 (vs 0.50 NQ, 1.25 ES)
- **3 micros** : risk = $3/tick
- **ATR median** : ~17 ticks/min (= 1.7 pts)
- **Range typique RTH** : 50-150 ticks (5-15 pts Gold)

## Range de ATR

- atr (per-bar, ticks) : min/max/median ATR du dataset
- atr_14m_pct : ATR normalisé % du prix

## Sessions UTC (sur la journée {TARGET_DATE})

- Asia : 00:00-06:00 UTC (~2:00-8:00 ET soir précédent → matin)
- London : 06:00-12:30 UTC (~01:00-07:30 ET)
- US Cash : 12:30-20:00 UTC (~07:30-15:00 ET, RTH actif)
- US After : 20:00-23:00 UTC

Gold cash open : 08:20 ET (= 12:20 UTC l'hiver, 13:20 UTC l'été DST).
Gold cash close : 13:30 ET (= 18:30 UTC l'été).
"""

readme_out = OUT_DIR / "README_GOLD_FEATURES.md"
readme_out.write_text(readme, encoding="utf-8")
print(f"\n  README  : {readme_out}")

print(f"\n=== EXPORT TERMINE ===")
print(f"  Dossier : {OUT_DIR}")
print(f"  Fichiers à envoyer à l'agent extérieur :")
print(f"    - gold_{TARGET_DATE.strftime('%Y%m%d')}_full.csv")
print(f"    - gold_{TARGET_DATE.strftime('%Y%m%d')}_full.parquet")
print(f"    - gold_{TARGET_DATE.strftime('%Y%m%d')}_menthorq_levels.json")
print(f"    - README_GOLD_FEATURES.md")
