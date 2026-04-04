# 📊 INVENTAIRE COMPLET — DUMPER (DMP_*) vs BOT (MIA_*)

**Date** : 01/03/2026
**Constat** : Le dumper G3 produit **142 features ML-ready**. Le bot en utilise **~25%**.
**Le dumper a été codé APRÈS le bot — ses features n'ont jamais été intégrées.**

---

## 🔴 BILAN SYNTHÉTIQUE

| Catégorie | Features Dumper | Utilisées Bot | **Écart** |
|-----------|:-:|:-:|:-:|
| VWAP (jour/week/month + SD bands) | 13 | 1 (slope seulement) | **12 manquantes** |
| Volume Profile Session (VPOC/VAH/VAL) | 5 | 3 (L1 + SLTP obstacles) | 2 manquantes |
| Volume Profile Veille (PV levels) | 9 | 6 (L1 + SLTP) | 3 manquantes |
| MenthorQ (GEX/HVL/Gamma/Blind) | 14 | 14 | ✅ Complet |
| Session & IB (Initial Balance) | 21 | **0** | **21 manquantes** |
| Composite Profiles (20d/50d) | 12 | 0 (SLTP seulement CP agrégé) | **12 manquantes** |
| OrderFlow / FPBS / Delta | 22 | ~10 (BN score, delta, CVD) | 12 manquantes |
| Bataille Navale signaux | 15 | 15 | ✅ Complet |
| Swing Structure | 6 | 2 (trend bias + SLTP) | 4 manquantes |
| **Open Type / Day Type / Règle 80%** | **9** | **0** | **🔴 9 manquantes** |
| **Profile Shape (D/P/b/B)** | **9** | **0** | **🔴 9 manquantes** |
| **HVN/LVN Session (VolumeAtPrice)** | **9** | **0** | **🔴 9 manquantes** |
| Booléens structurels | 13 | 0 | **13 manquantes** |
| **TOTAL** | **~157** | **~51** | **~106 features inutilisées** |

---

## 🔴🔴🔴 FEATURES CRITIQUES — DISPONIBLES, JAMAIS UTILISÉES (0 références)

### 1. CONTEXTE MARCHÉ (DMP_OpenType.h) — 9 features, 0 dans le bot

| Feature Dumper | Type | Impact Trading | Dans le Bot |
|---|---|---|:-:|
| `open_type` | enum 0-11 (OD_UP/DOWN, OTD, ORR, OAIR, OAOR, ODF) | **FONDAMENTAL** — Détermine si c'est un Trend Day ou Range Day | ❌ |
| `open_zone` | enum 1-7 (position vs PDH/PDL/VA) | **CRITIQUE** — Biais directionnel de la session | ❌ |
| `open_bias_conf` | float 0.0-1.0 | Confiance du biais (OD=0.85, OAIR=0.30) | ❌ |
| `open_direction` | -1/0/+1 | Direction encodée pour filtrage | ❌ |
| `day_type` | enum 0-4 (NonTrend/Normal/NormVar/Neutral/Trend) | **CRITIQUE** — Adapte SL/TP/sizing au type de journée | ❌ |
| `rule_80pct` | 0/1 | **HAUTE CONVICTION** — 80% de traverser la VA | ❌ |
| `trend_day_probability` | float 0.0-1.0 | Probabilité Trend Day en temps réel | ❌ |
| `ma_trend` | -1/+1 | Tendance long terme (MA fast vs slow) | ❌ |
| `vwap_ma_align` | 0/1 | Alignement VWAP + MA (confluence tendance) | ❌ |

**Impact** : Le bot trade en aveugle — il ne sait pas s'il est dans un Trend Day (suivre) ou un Range Day (fader). Il applique les mêmes règles SL/TP/trailing que le marché soit en tendance forte ou en rotation.

---

### 2. PROFILE SHAPE (DMP_ProfileShape.h) — 9 features, 0 dans le bot

| Feature Dumper | Type | Impact Trading | Dans le Bot |
|---|---|---|:-:|
| `profile_shape` | 0=D/1=P/2=b/3=B | **CRITIQUE** — D=range, P=bullish, b=bearish, B=breakout | ❌ |
| `profile_skew` | float -1.0 à +1.0 | Asymétrie du volume (>0=bullish) | ❌ |
| `poc_position` | float 0.0-1.0 | Position POC dans range (haut=P, bas=b) | ❌ |
| `volume_imbalance` | float ratio | Volume upper/lower (>1=acheteurs dominent) | ❌ |
| `is_double_dist` | 0/1 | Double distribution détectée (breakout imminent) | ❌ |
| `poc_separation_ticks` | float | Distance entre 2 POC (B-shape) — mesure tension | ❌ |
| `single_print_mid` | float prix | Zone de single prints (passage rapide) | ❌ |
| `single_print_count` | int | Densité single prints (plus = tendance forte) | ❌ |
| `profile_hvn_dominant` | float prix | HVN dominant session (noeud attraction) | ❌ |

**Impact** : Le bot ne sait pas si le profil est en cloche (D=fader) ou asymétrique (P/b=suivre). Il ne détecte pas les doubles distributions (B=explosion de prix imminente).

---

### 3. HVN/LVN SESSION via VolumeAtPriceForBars (DMP_HVN_LVN.h) — 9 features, 0 dans le bot

| Feature Dumper | Type | Impact Trading | Dans le Bot |
|---|---|---|:-:|
| `dist_session_hvn_above` | float ticks | HVN obstacle au-dessus (résistance volume) | ❌ |
| `dist_session_hvn_below` | float ticks | HVN support en-dessous | ❌ |
| `dist_session_lvn_above` | float ticks | LVN au-dessus = zone de passage rapide (bon TP) | ❌ |
| `dist_session_lvn_below` | float ticks | LVN en-dessous = passage rapide | ❌ |
| `session_hvn_count` | int | Densité HVN ±100 ticks (marché congestionné?) | ❌ |
| `session_lvn_count` | int | Densité LVN ±100 ticks (marché ouvert?) | ❌ |
| `lvn_between` | 0/1 | LVN entre prix et TP → prix accélère ✅ | ❌ |
| `hvn_between` | 0/1 | HVN entre prix et TP → obstacle ⛔ | ❌ |
| `lvn_confluence_count` | int | Cluster de LVN (zone de vide massive) | ❌ |

**Impact** : Le bot utilise les LVN/HVN des Composite Profiles (sg17/sg18 = N/A !) dans SLTP_Calc, mais PAS les vrais HVN/LVN calculés par VolumeAtPriceForBars. Il a des structures vides là où le dumper a des données réelles.

---

### 4. SESSION & IB (Initial Balance) — 21 features, 0 dans le bot

| Feature Dumper | Type | Impact Trading | Dans le Bot |
|---|---|---|:-:|
| `dist_ib_high` | float ticks | Distance au IB High (résistance/breakout) | ❌ |
| `dist_ib_low` | float ticks | Distance au IB Low (support/breakdown) | ❌ |
| `ib_range_ticks` | float | Taille IB = prédit le type de journée | ❌ |
| `ib_range_atr` | float ratio | IB/ATR → <0.4=comprimé, >0.8=trend | ❌ |
| `ib_is_narrow` | 0/1 | IB étroite → breakout probable | ❌ |
| `ib_is_wide` | 0/1 | IB large → trend day en cours | ❌ |
| `ib_position_pct` | float 0-1 | Position dans IB (haut/bas) | ❌ |
| `ib_broken_up` | 0/1 | IB High cassé → extension haussière | ❌ |
| `ib_broken_down` | 0/1 | IB Low cassé → extension baissière | ❌ |
| `ib_complete` | 0/1 | IB formée (après 10h30) | ❌ |
| `dist_sess_high/low` | float ticks | Distance aux extrêmes session | ❌ |
| `dist_open_cash` | float ticks | Distance à l'open 9h30 (pivot intraday) | ❌ |
| `dist_ovn_high/low` | float ticks | Distance overnight high/low | ❌ |
| `open_gap_ticks` | float | Gap entre open et PVPOC | ❌ |
| `open_position` | -2 à +2 | Position open vs VA veille | ❌ |

**Impact** : Le bot ne sait pas si l'IB est large (trend day) ou étroite (breakout à venir). Il ne détecte pas les cassures IB qui sont parmi les setups les plus fiables.

---

### 5. VWAP SD BANDS — 12 features, 0 position/bands dans le bot

| Feature Dumper | Type | Impact Trading | Dans le Bot |
|---|---|---|:-:|
| `dist_vwap_d` | float ticks | Distance au VWAP jour | ❌ (slope oui, distance non) |
| `dist_vwap_d_sd1u/sd1d` | float ticks | Distance aux bandes SD±1 | ❌ |
| `dist_vwap_d_sd2u/sd2d` | float ticks | Distance aux bandes SD±2 (extrêmes) | ❌ |
| `dist_vwap_w/m` | float ticks | Distance VWAP weekly/monthly | ❌ |
| `vwap_d/w/m_side` | -1/+1 | Position vs les 3 VWAPs | ❌ |
| `vwap_triple_align` | -1/0/+1 | Prix au-dessus/dessous des 3 VWAPs | ❌ |

**Impact** : Le bot utilise `vwap_slope` (direction) mais ne sait pas si le prix est à SD+2 (surévalué → retour probable) ou SD-2 (sous-évalué → rebond probable). La symétrie SD+2→SD-2 est complètement absente.

---

### 6. BOOLÉENS STRUCTURELS — 13 features, 0 dans le bot

| Feature Dumper | Type | Impact Trading | Dans le Bot |
|---|---|---|:-:|
| `bool_above_cur_vpoc` | 0/1 | Au-dessus du VPOC courant? | ❌ |
| `bool_above_prev_vpoc` | 0/1 | Au-dessus du PVPOC? | ❌ |
| `bool_above_vwap_d/w/m` | 0/1 | Position vs 3 VWAPs | ❌ |
| `bool_above_mq_hvl` | 0/1 | Au-dessus du HVL (gamma regime) | ❌ |
| `bool_near_level` | 0/1 | Proche d'un niveau clé? | ❌ |
| `bool_ib_inside` | 0/1 | Dans l'IB? | ❌ |
| `bool_session_early` | 0/1 | Avant 10h00 (marché instable) | ❌ |
| `bool_va_confluence` | 0/1 | VPOC courant ≈ PVPOC | ❌ |
| `bool_gex_flip_zone` | 0/1 | Zone de flip gamma | ❌ |

---

## ✅ CE QUE LE BOT UTILISE BIEN (référencé dans MIA_Layers.h / MIA_SLTP_Calc.h)

| Catégorie | Détail | Fichier | Références |
|---|---|---|:-:|
| **MenthorQ complet** | GEX 1-10, HVL, Gamma, Call/Put, Blind, VWAP MQ | MIA_Layers.h L1 | 88 |
| **BN complet** | Edge, Color, Absorb, Rotation, Score, Momentum | MIA_Layers.h L2 | 169 |
| **VWAP slope + delta** | vwap_slope, momentum_score, deltaPct, smart_money | MIA_Layers.h L3 | 55 |
| **PV Levels en L1** | prev_vpoc(+3), prev_vah(+2), prev_val(+2), prev_vwap(+1) | MIA_Layers.h | ✅ |
| **Session VP en SLTP** | session_vah, session_val, VPOC comme obstacles | MIA_SLTP_Calc.h | ✅ |
| **Swing H/L** | trend_bias (L3) + SL structurel (SLTP) | Layers + SLTP | 2+8 |
| **CP LVN agrégé** | nearest_lvn_above/below pour TP rapide | MIA_SLTP_Calc.h | ✅ |
| **CVD Divergence** | delta_div_buy/sell + veto (L2) | MIA_Layers.h | ✅ |
| **VIX Regime** | GetVIXMultiplier() ajuste SL/TP | MIA_SLTP_Calc.h | ✅ |

---

## 🎯 MATRICE D'IMPACT — QUOI INTÉGRER EN PREMIER ?

### TIER 1 — Impact maximal, complexité minimale (FONDATION du nouveau framework)

| Feature | Impact | Pourquoi | Complexité |
|---|:-:|---|:-:|
| **open_type** (12 valeurs) | ⭐⭐⭐⭐⭐ | Détermine le RÉGIME de la journée entière | Moyenne |
| **open_zone** (7 zones) | ⭐⭐⭐⭐⭐ | Biais directionnel (imbalance vs balance) | Faible |
| **day_type** (5 valeurs) | ⭐⭐⭐⭐⭐ | Adapte SL/TP/sizing/type de trades autorisés | Moyenne |
| **ib_range_atr** + **ib_broken** | ⭐⭐⭐⭐⭐ | IB = cadre de référence intraday #1 | Faible |
| **rule_80pct** | ⭐⭐⭐⭐ | Signal haute conviction (80% win rate théorique) | Faible |

→ **Ces 5 features créent le Layer 0 — RÉGIME** qui n'existe pas du tout aujourd'hui.

### TIER 2 — Améliore la précision des entrées/sorties

| Feature | Impact | Pourquoi | Complexité |
|---|:-:|---|:-:|
| **profile_shape** (D/P/b/B) | ⭐⭐⭐⭐ | Confirme/invalide le biais (P=ne pas shorter) | Faible |
| **dist_vwap_d + SD bands** | ⭐⭐⭐⭐ | SD+2 = surévalué, SD-2 = sous-évalué | Faible |
| **vwap_triple_align** | ⭐⭐⭐ | Alignement des 3 VWAPs = tendance forte | Faible |
| **HVN/LVN session** (VolumeAtPrice) | ⭐⭐⭐⭐ | Remplace les sg17/sg18 N/A — vrais niveaux | Haute |
| **dist_open_cash** | ⭐⭐⭐ | Open comme pivot intraday | Faible |

→ **Ces features enrichissent Layer 1 (zones) et Layer 2 (filtres).**

### TIER 3 — Optimisation fine

| Feature | Impact | Pourquoi | Complexité |
|---|:-:|---|:-:|
| **Booléens structurels** (13) | ⭐⭐ | Filtres rapides pré-calculés | Faible |
| **Composite 20d/50d** | ⭐⭐ | Contexte macro (pas critique intraday) | Faible |
| **FPBS avancé** (vol_per_sec, finish_strength) | ⭐⭐ | Micro-timing d'entrée | Faible |
| **ovn_high/low** | ⭐⭐ | Niveaux overnight (gaps) | Faible |

---

## 🏗️ LE GAP ARCHITECTURAL — POURQUOI ÇA NE MATCHE PAS

```
DUMPER (DMP_*)                          BOT (MIA_*)
═══════════════                         ═══════════════
DMP_OpenType.h                          (rien)
  → open_type, day_type, rule_80%       
  → open_zone, open_direction           
  → trend_day_probability               

DMP_ProfileShape.h                      (rien)
  → profile_shape D/P/b/B              
  → profile_skew, poc_position          
  → is_double_dist, single_prints       

DMP_HVN_LVN.h                          MIA_Config.h
  → VolumeAtPriceForBars               → session_hvn/lvn (champs dans BN_Data)
  → 5 HVN + 5 LVN above/below         → MAIS jamais remplis !
  → distances, confluence, between     → sg17/sg18 = N/A (source morte)

DMP_Transform.h                         MIA_Layers.h
  → 142 features normalisées           → Lit les prix BRUTS de MenthorQ/BN
  → Distances en ticks ET ATR           → Calcul inline à chaque évaluation
  → IB complète, SD bands              → Pas d'IB, pas de SD bands
  → Open gap, overnight, session       → Pas de contexte session

DMP_Writer.h                            MIA_DataDumper.h
  → JSONL format structuré              → JSONL aussi (format v2)
  → 142 features à chaque barre        → 170+ champs bruts
  → Optimisé ML                        → Optimisé trading live
```

**Le problème fondamental** : Le dumper transforme les données brutes en features intelligentes
(distances normalisées, contexte calculé, régimes classifiés). Le bot lit les mêmes données
brutes mais les interprète avec une logique figée (Layer 1-4) sans aucun contexte dynamique.

---

## 📋 PLAN D'ACTION RECOMMANDÉ

### Phase 1 — Collecter les données (MAINTENANT, avant de coder le bot)

Le dumper G3 est prêt. Faire tourner en RTH pendant 2-3 semaines pour avoir :
- Les JSONL avec open_type, day_type, profile_shape sur données réelles
- Valider que les HVN/LVN via VolumeAtPriceForBars sont cohérents
- Avoir une base pour backtester le nouveau framework

### Phase 2 — Analyser en Python (1-2 semaines)

Avec les données collectées :
1. Win rate par open_type (OD vs OAIR vs ORR)
2. Fiabilité de la Règle des 80%
3. HVN/LVN comme niveaux de réaction (prix bounce-t-il?)
4. Profile Shape comme prédicteur de la suite
5. IB range vs type de journée réel

### Phase 3 — Intégrer dans le bot (itératif)

Seulement APRÈS validation data-driven :
1. Ajouter les structures manquantes dans MIA_Config.h
2. Implémenter les calculs dans MIA_Indicators.h ou nouveau MIA_MarketProfile.h
3. Créer le Layer 0 (Régime) dans MIA_Layers.h
4. Adapter les Layers existants selon le régime
5. Tester en MODE_TEST

---

*Ce document est la photo exacte de l'état au 01/03/2026.*
*Toute feature du dumper non listée dans "utilisées" = feature morte côté bot.*
