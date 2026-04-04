# MenthorQ — Catalogue complet des données disponibles
## Date : 01/04/2026 | Plan : PRIME

---

## 1. ASSETS COUVERTS (1300+ tickers)

### Index Futures (notre focus)
| Ticker | Nom | Données dispo |
|--------|-----|---------------|
| **ES1!** | E-Mini S&P 500 | ✅ Gamma, Q-Score, GEX, DEX, Swing, Blind Spots, Option Matrix |
| **NQ1!** | E-Mini NASDAQ-100 | ✅ Idem |
| **RTY1!** | E-Mini Russell 2000 | ✅ Idem |

### Energy Futures
| Ticker | Nom |
|--------|-----|
| CL | Crude Oil WTI |
| NG | Natural Gas |

### Metals Futures
| Ticker | Nom |
|--------|-----|
| GC | Gold |
| SI | Silver |
| PL | Platinum |
| HG | Copper |

### Fixed Income / Rates
| Ticker | Nom |
|--------|-----|
| ZN | 10-Year Treasury Note |
| ZT | 2-Year Treasury Note |
| ZB | 30-Year Treasury Bond |
| ZF | 5-Year Treasury Note |

### Forex Futures
| Ticker | Paire |
|--------|-------|
| 6A | AUD/USD |
| 6B | GBP/USD |
| 6C | CAD/USD |
| 6E | EUR/USD |
| 6J | JPY/USD |
| 6S | CHF/USD |

### Crypto Futures
| Ticker | Nom |
|--------|-----|
| MBT | Micro Bitcoin |

### Soft Commodities
| Ticker | Nom |
|--------|-----|
| ZW | Wheat |
| ZS | Soybeans |
| ZC | Corn |

### Indices Cash
| Ticker | Nom |
|--------|-----|
| SPX | S&P 500 |
| QQQ | NASDAQ ETF |
| VIX | Volatility Index |

### Stocks & ETFs
- 1000+ actions et ETFs avec Gamma Levels et Q-Score

---

## 2. MODÈLES QUANTITATIFS

### A. Gamma Exposure (GEX)
- **Net GEX** — Exposition gamma nette (positif=stable, négatif=instable)
- **Total GEX** — Exposition gamma totale
- **GEX par expiration** — Tableau avec GEX/DEX par date d'expiry
- **GEX par strike** — Top 10 strikes avec gamma exposure
- **Gamma Condition** — Positif / Négatif
- **Gamma Flip Zone** — Prix où gamma passe de + à -
- **0DTE GEX** — Gamma exposure same-day expiration
- Disponible pour : Futures, Indices, Stocks, ETFs

### B. Delta Exposure (DEX)
- **Net DEX** — Exposition delta nette
- **Total DEX** — Exposition delta totale
- **P/C DEX ratio** — Put/Call delta ratio
- Disponible par expiration

### C. Q-Score (4 composantes)
- **Option Score** (0-5) — Positionnement options bull/bear
- **Volatility Score** (0-5) — Régime de volatilité
- **Momentum Score** (0-5) — Élan directionnel
- **Seasonality Score** (-5 to +5) — Saisonnalité
- Score agrégé = signal directionnel composite

### D. Niveaux Clés
- **Call Resistance** — Résistance options calls
- **Put Support** — Support options puts
- **HVL** (High Volume Level) — Niveau de volume élevé
- **Call/Put 0DTE** — Niveaux intraday
- **Gamma Wall 0DTE** — Mur gamma intraday
- **1D Max / 1D Min** — Range journalier projeté (Expected Move)

### E. Swing Trading Model (ML)
- **Upper Band** — Résistance swing (5-20 jours)
- **Lower Band** — Support swing
- **Risk Trigger** — Niveau de déclenchement du risque
- **Biais directionnel** — Haussier / Baissier / Neutre
- Machine learning avec prédictions 5J et 20J

### F. Blind Spots Levels
- **BL1 à BL10** — 10 niveaux de zones de réaction cachées
- Algorithme propriétaire MenthorQ (cross-asset correlation)

### G. Volatility Models
- **Implied Vol 30D** — Volatilité implicite 30 jours
- **Expected Move %** — Déplacement attendu ±%
- **Volatility Surface** — Vue 3D IV par strike × expiry
- **Volatility Smile** — IV par strike
- **Volatility Skew** — Asymétrie IV
- **VRP** (Volatility Risk Premium) — Prime de risque vol

### H. Open Interest & Volume
- **P/C OI ratio** — Put/Call Open Interest
- **P/C Volume ratio** — Put/Call Volume
- **OI par strike et expiration**
- **Volume par strike et expiration**

### I. Option Matrix
- Chaîne d'options complète par expiration
- GEX, DEX, OI, Volume par strike
- Niveaux clés dérivés (Call Res, Put Sup, HVL) par expiry
- Expected Move par expiry
- Disponible pour tous les tickers

### J. CTA Models
- Positionnement des fonds CTA (Commodity Trading Advisors)
- Niveaux de déclenchement d'achat/vente
- Confirmation de tendance

### K. Momentum Models
- Indicateurs techniques avancés
- Assessment de prix, volatilité, volume
- Prédiction de changement de tendance

---

## 3. SCREENERS (filtres de marché)

| Screener | Données filtrées |
|----------|-----------------|
| Gamma | Condition gamma (positif/négatif), Net GEX |
| Gamma Levels | Niveaux gamma par ticker |
| Open Interest | Variation OI, P/C ratio |
| Volatility | IV rank, VRP, IV percentile |
| Volume | Volume inhabituel, ratio P/C volume |
| Q-Score | Score composite, momentum, saisonnalité |

---

## 4. INTÉGRATIONS

| Plateforme | Type |
|-----------|------|
| **Sierra Chart** | API niveaux gamma (déjà utilisé) |
| TradingView | Indicateur gamma levels |
| NinjaTrader | Plugin |
| ATAS | Plugin |
| Quantower | Plugin |
| Bookmap | Plugin |
| MotiveWave | Plugin |
| EdgeClear | Plugin |
| TrendSpider | Plugin |
| Tickblaze | Plugin |

---

## 5. CE QU'ON COLLECTE DÉJÀ vs CE QU'ON PEUT AJOUTER

### ✅ Déjà collecté (API Sierra Chart — temps réel)
- Call Resistance, Put Support, HVL
- Call/Put 0DTE, Gamma Wall 0DTE
- GEX 1-10 (strikes)
- Blind Spots BL1-BL10
- 1D Max / 1D Min
- VIX levels

### ✅ Récupéré via OpenClaw (daily — validé 31/03)
- Q-Score (4 composantes)
- Gamma Condition (Positif/Négatif)
- Gamma Flip Zone
- Net GEX, Total GEX, Expiring GEX
- Net DEX, Total DEX
- P/C ratios (GEX, DEX, OI, Volume)
- IV 30D, Expected Move %
- Distance to HVL %
- Top 10 GEX strikes avec valeurs
- Tableau expirations complet (DTE, GEX, DEX, P/C, HVL, Call/Put par expiry)

### ❌ À récupérer (prochaine étape)
- **Swing Trading Levels** (Upper/Lower Band, Risk Trigger)
- **CTA Models** (positionnement CTA, trigger levels)
- **Volatility Surface / Smile / Skew**
- **Option Matrix détaillée** (chaîne d'options complète)
- **Données cross-asset** (Gold GC, Oil CL, Bonds ZN, EUR 6E)
- **Momentum Models**

---

## 6. IMPACT ML — Features macro pour LightGBM

### Priorité 1 (TRÈS HAUT — déjà récupéré)
| Feature | Source | Type |
|---------|--------|------|
| qscore_option | OpenClaw | Daily |
| qscore_volatility | OpenClaw | Daily |
| qscore_momentum | OpenClaw | Daily |
| qscore_seasonality | OpenClaw | Daily |
| gamma_condition | OpenClaw | Daily (-1/+1) |
| net_gex_m | OpenClaw | Daily |
| pc_oi | OpenClaw | Daily |
| iv_30d | OpenClaw | Daily |
| exp_move_pct | OpenClaw | Daily |

### Priorité 2 (HAUT — à récupérer)
| Feature | Source | Type |
|---------|--------|------|
| swing_upper | OpenClaw | Daily |
| swing_lower | OpenClaw | Daily |
| swing_risk_trigger | OpenClaw | Daily |
| gamma_flip_zone | OpenClaw | Daily |
| dominant_expiry_gex_pct | OpenClaw | Daily |
| cta_trigger_level | OpenClaw | Daily |

### Priorité 3 (MOYEN — cross-asset)
| Feature | Source | Type |
|---------|--------|------|
| gold_gamma_condition | OpenClaw GC | Daily |
| oil_gamma_condition | OpenClaw CL | Daily |
| bonds_gamma_condition | OpenClaw ZN | Daily |
| eur_gamma_condition | OpenClaw 6E | Daily |
| vix_qscore | OpenClaw VIX | Daily |

---

## 7. API MENTHORQ (découverte via OpenClaw)

### Endpoint AJAX WordPress
- URL : `{site}/wp-admin/admin-ajax.php`
- Action : `get_command`
- Params : `security={nonce}`, `command_slug={slug}`, `ticker={ticker}`, `date={date}`
- Auth : Cookie WordPress `wordpress_logged_in_*`

### Slugs COMPLETS (extraits du QDataParams)

#### Futures (`commands=futures`)
`qscore_option`, `qscore_momentum`, `qscore_volatility`, `qscore_seasonality`,
`netgex`, `netgex_multiexpiry`, `key_levels`, `bl_levels`, `matrix_v1`,
`future_curve`, `levels_tv`

#### EOD Indices/Stocks (`commands=eod`)
`qscore_option`, `qscore_momentum`, `qscore_volatility`, `qscore_seasonality`,
`liq_snapshot`, `key_levels`, `netgex`, `netgex_multiexpiry`, `levels_tv`,
`matrix`, `voloi`, `voloi_0dte`, `mainchart`, `swing_5d`, `swing_20d`,
`swing_levels`, `bl_levels`, `skew`, `skew_0dte`, `skew_3m`, `term`,
`net_dex`, `ivoi`, `oi`, `vol_smile`, `vol_surface_3d`, `vol_surface_2d`, `vrp`

#### Intraday (`commands=intraday`)
`netgex_0dte`, `netgex_intraday`, `vol_0dte_intraday`, `liquidity_summary`,
`levels_tv_intraday`, `gex_diff_vs_eod`, `gex_diff_vs_last`

#### CTAs (`commands=cta`)
`cta_table`, `cta_index`, `cta_currency`, `cta_commodity`, `cta_spx`,
`cta_nasdaq`, `cta_wti`, `cta_brent`, `cta_gold`, `cta_silver`,
`cta_copper`, `cta_natgas`, `cta_treasury2y`, `cta_treasury10y`

#### Vol Models (`commands=vol`)
`vol_control`, `vol_barometer`, `market_breadth`, `rsi_bollinger`,
`ma_indicator`, `macd_indicator`, `super_trend`, `vrp_dashboard`, `hv_vs_iv`

#### Note : Swing Models = SPX (proxy ES), QQQ (proxy NQ)

### Workflow automatisé
1. Login WordPress (POST /wp-login.php)
2. Récupérer nonce depuis la page dashboard
3. Appeler `get_command` pour chaque slug × ticker
4. Parser le JSON/HTML retourné
5. Sauvegarder dans DATA/MENTHORQ/

---

*Document généré le 01/04/2026 — MIA Trading System*
