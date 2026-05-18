# Bot 3 V1 Baseline — 11 jours (4-18 mai 2026)

**Date audit** : 2026-05-18 Phase 0.5
**Data source** : `LOGS/trading/trading_2026*_paper_v2.jsonl` (11 fichiers VPS)
**Périmètre** : Bot 3 v1 paper Sim1 sur 11 jours trading (4 mai → 18 mai 2026)

## Constat critique : diagnostic 15-18/05 était échantillon biaisé

Le diagnostic initial "Bot 3 v1 catastrophique WR 13% weekend 15-18/05" était basé sur 15 trades sur 2 jours bearish uniformes. **Pas représentatif** de la performance moyenne du bot.

## Métriques réelles 11 jours

| Métrique | Valeur |
|----------|--------|
| Total events | 282 |
| Trades opened | **152** |
| Trades closed | 130 |
| Trades par jour (moyenne) | **~14** |
| LONG ratio | **80.3%** (vs 93% sur 2j 15-18/05) |
| SHORT ratio | 19.7% (30 trades) |
| TP closes | 25 |
| SL closes | 32 |
| TIMEOUT closes | 46 |
| RECOVERED_TIMEOUT | 24 (force close après restart) |
| SHUTDOWN_OPEN | 3 |
| WR brut (TP / (TP+SL)) | **43.9%** |
| WR avec timeouts loss | ~16-20% (pessimiste, dépend si timeout = loss) |

## Trades par jour

| Date | Trades |
|------|--------|
| 2026-05-04 | 29 |
| 2026-05-05 | 9 |
| 2026-05-06 | 26 |
| 2026-05-07 | 8 |
| 2026-05-08 | 13 |
| 2026-05-11 | 17 |
| 2026-05-12 | 13 |
| 2026-05-13 | 13 |
| 2026-05-14 | 9 |
| 2026-05-15 | 12 |
| 2026-05-18 | 3 |

## Niveaux les plus fired

| Niveau | Trades | % total |
|--------|--------|---------|
| GEX_DN | **75** | 49.3% |
| CUR_VPOC | 20 | 13.2% |
| MQ_CALL_POC_FLAT | 15 | 9.9% |
| MQ_PUT_0DTE | 13 | 8.6% |
| VWAP_W_SD1D | 10 | 6.6% |
| OPEN_830 | 7 | 4.6% |
| SINGLE_PRINT | 5 | 3.3% |
| PVAL | 2 | 1.3% |
| MQ_HVL | 2 | 1.3% |
| IB_LOW | 2 | 1.3% |

**Constat** : GEX_DN (LONG par construction dict) = 49% des trades = le plus gros producteur de pertes potentielles, pas MQ_PUT_0DTE.

## Implications pour Bot 3 v2

### Cible WR Phase 5 GO

Le plan original cible **WR ≥40%** Phase 5 walk-forward.

**Révision** : baseline réelle Bot 3 v1 ≈ 43.9% WR (TP/TP+SL). Si Bot 3 v2 atteint 43.9% → **pas un gain**. Cible doit être :
- **Critère minimal** : WR brut Bot 3 v2 ≥ WR brut Bot 3 v1 + 10pp = **≥53.9%**
- **Critère ambitieux** : WR brut Bot 3 v2 ≥ 60% + reduction timeouts ≥50%

### Cible bidirectional ratio Phase 5 GO

Le plan original cible bidirectional 40-60% LONG/SHORT.

**Révision** : baseline réelle 80.3% LONG / 19.7% SHORT. Bot 3 v2 doit :
- **Critère minimal** : SHORT ratio ≥ 35% (vs 19.7%)
- **Critère ambitieux** : SHORT ratio 40-50% (équilibre proche neutre)

### Cible reduction timeouts

Le plan original ne ciblait pas explicitement timeouts.

**Révision** : 46+24 = 70 / 152 trades = **46% des trades en timeout**. C'est énorme. Bot 3 v2 avec ConfirmationGate intégré + ScenarioValidator INVALIDATED early exit doit :
- **Critère minimal** : timeouts ≤ 30% des trades
- **Critère ambitieux** : timeouts ≤ 20%

### Impact sur Phase 5 DSR

Pour DSR Lopez Phase 5 : 152 trades sur 11 jours = ~14/jour. Sur 12 mois extrapolés = ~3000 trades total. Avec 7 scenarios canonical (ADR 0001) = **~430 trades par scenario** = **CONFORTABLE pour DSR ≥0.95**.

→ ADR 0001 Levier 2 (étendre 12 mois) **validé empiriquement**.

## Limitations baseline

- **N = 11 jours** : représentatif d'1 quinzaine, pas annuel
- Pas de seasonal effect (FOMC, quad witching, year-end)
- Couvre 1 régime macro (mai 2026 bearish-to-mixed)
- Pas de baseline Phase 6 shadow (multi-scenarios fired simultanés)

**Action Phase 5 prerequis** : runner audit baseline sur 12 mois data v3 (cf ADR 0001 Levier 2).

## Methodologie

Script ad-hoc Python : parse JSONL trading logs → group by `code` → analyse `ctx`. Inclut tous les events `BOT3_TRADE_OPEN` + `BOT3_TRADE_CLOSE`. Pas de filtrage par symbole.

Distinct des logs `LOGS/decisions/decisions_*_paper_v2.jsonl` qui contiennent les decisions BOT3_REGIME_OBSERVE + BOT3_LEVEL_CONTACT + BOT3_DECISION_SKIP (volume beaucoup plus important).

## Cross-references

- ADR `DOCS/ADR/0001-dsr-statistical-design.md`
- Master plan `DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md` section "Mesures succès chiffrées"
- INCIDENT_LOG `DOCS/INCIDENT_LOG.md` entry 2026-05-18 Pattern 11 V1 inversé (à corriger : 13% WR était sample biaisé, vraie baseline ~44%)
