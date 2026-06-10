# Bot 2 Scenario Manager — Design (Solution A)

**Date** : 25/05/2026
**Contexte** : Solution B (ML directional) NOGO sur baseline correct (edge reel +0.17 PF, +2.4 ticks vs random uniforme). On revient sur Solution A — Scenario Manager.

## Concept

Plutot que trader bar-par-bar avec scoring instantane, le bot maintient un **scenario actif** sur plusieurs heures.

Multi-timeframe :
- **15m** : context macro (regime trend / range / breakout)
- **1m** : timing entry / exit

## Scenarios candidats (5)

### 1. BREAKOUT_PULLBACK (LONG/SHORT)
- Detection : cassure HVN/PDH/PDL + pullback failed (close au dessus du level pendant 5+ bars 1m)
- Entry : 1ere bar 1m qui montre rejection du retest (long_up_bar + delta+)
- TP : niveau institutionnel suivant (next dist_*_pct > 0)
- SL : sous le level cassure - 2 ticks
- Invalidation : close < level cassure - ATR * 0.5
- Holding max : 4h

### 2. RANGE_FADE (LONG/SHORT)
- Detection 15m : oscillation entre VAH et VAL (PDH/PDL) sur 6+ bars 15m sans cassure
- Entry : touche VAL (LONG) ou VAH (SHORT) avec rejection footprint
- TP : VPOC (cur_vpoc)
- SL : 8 ticks au-dela du level touche
- Invalidation : cassure du range sur 2 bars 1m consecutives
- Holding max : 2h

### 3. TREND_CONTINUATION (LONG/SHORT)
- Detection : vwap_slope_30 monotone sur 60 bars 1m (1h) ET HH/HL Dow
- Entry : pullback a VWAP ou SD1 (LONG) / VWAP ou SD1u (SHORT)
- TP : SD2 oppose
- SL : SD1 oppose
- Invalidation : cassure du trend (close du mauvais cote VWAP > 5 bars)
- Holding max : 6h

### 4. MEAN_REVERSION_SD2 (LONG/SHORT)
- Detection : prix touche SD2u (SHORT) ou SD2d (LONG) avec exhaustion
  - Pour SHORT @ SD2u : long_up_bar PUIS long_dn_bar dans 3 bars + delta_pct flip
- Entry : sur la bar de flip
- TP : VWAP_d
- SL : SD3 (ou +12 ticks)
- Invalidation : 2 bars consecutives au-dela de SD3
- Holding max : 3h

### 5. OPENING_RANGE_BREAK (LONG/SHORT)
- Detection : premiere heure RTH (09:30-10:30 ET) range etabli
- Entry : cassure du range + close 3 bars au-dela + retest valide
- TP : range_width * 1.5
- SL : milieu du range
- Holding max : EOD (16:00 ET)

## Architecture

```python
@dataclass
class Scenario:
    id: str
    type: str  # "BREAKOUT_PULLBACK", etc.
    direction: str  # "long" / "short"
    activated_at: pd.Timestamp
    entry_conditions: dict
    target_level: float
    stop_level: float
    invalidation: dict
    holding_max_min: int
    confidence: float  # 0.0-1.0
    state: str  # "ARMED", "ACTIVE", "TRIGGERED", "CLOSED", "INVALIDATED"

class ScenarioManager:
    def __init__(self, symbol: str, params: dict):
        self.symbol = symbol
        self.active_scenarios: list[Scenario] = []
        self.history: list[Scenario] = []

    def update(self, bar_1m, bar_15m, levels):
        # 1. Detecter nouveaux scenarios sur close 15m
        if bar_15m.is_close:
            new_scens = self._detect_scenarios(bar_15m, levels)
            self.active_scenarios.extend(new_scens)

        # 2. Update active scenarios sur close 1m
        for s in self.active_scenarios:
            if self._check_invalidation(s, bar_1m):
                s.state = "INVALIDATED"
                continue
            if s.state == "ARMED" and self._check_entry_trigger(s, bar_1m):
                s.state = "TRIGGERED"
                s.entry_price = bar_1m.close
                s.entry_ts = bar_1m.ts
                # emit trade signal

        # 3. Cleanup
        self.history.extend([s for s in self.active_scenarios
                              if s.state in ("INVALIDATED", "CLOSED")])
        self.active_scenarios = [s for s in self.active_scenarios
                                  if s.state in ("ARMED", "ACTIVE", "TRIGGERED")]

    def get_trade_signal(self) -> Optional[TradeSignal]:
        triggered = [s for s in self.active_scenarios if s.state == "TRIGGERED"
                     and not s.consumed]
        if not triggered:
            return None
        # Prioriser par confidence
        best = max(triggered, key=lambda x: x.confidence)
        best.consumed = True
        return TradeSignal(
            symbol=self.symbol,
            direction=best.direction,
            entry=best.entry_price,
            sl=best.stop_level,
            tp=best.target_level,
            holding_max_min=best.holding_max_min,
            metadata={"scenario_type": best.type, "scenario_id": best.id},
        )
```

## Difference vs BN V4

| Aspect | BN V4 | Scenario Manager |
|--------|-------|------------------|
| Timeframe entry | 1m bar-by-bar | 15m context + 1m entry |
| Holding | 90 bars 1m (1.5h) | 2-6h selon scenario |
| Detection | Toutes les bars 1m | Sur close 15m + retest 1m |
| Variable | 1 setup unique | 5 scenarios distincts en parallele |
| Risk | SL fixe en ticks | SL au level invalidation |
| TP | R:R fixe ou trailing Dow | Target niveau institutionnel |

## Plan d'implementation (5 jours)

### Jour 1 : Detection 15m + multi-tf join
- Resample parquet 1m -> 15m (volume, vwap, slopes)
- Calcul VWAP_15m + SD bands 15m
- Join MenthorQ daily levels

### Jour 2 : Scenarios 1-2 (BREAKOUT_PULLBACK + RANGE_FADE)
- Logique detection sur 15m
- Trigger entry sur 1m
- Tests unitaires

### Jour 3 : Scenarios 3-5
- TREND_CONTINUATION, MEAN_REVERSION_SD2, OPENING_RANGE_BREAK
- Verifier non-overlap (priorite si plusieurs scenarios sur meme symbol)

### Jour 4 : Backtest naif (6 mois NQ)
- Pas de walk-forward Lopez initial (juste comptage + PF par scenario)
- Verdict par scenario : "garder", "ameliorer", "abandonner"

### Jour 5 : Integration Bot 2
- ScenarioManager dans bn_v4_paper.py (remplace BNV4Engine)
- Mode shadow 5 jours
- Validation avec Jackson

## Estimation initiale par scenario (avant backtest)

Basee sur l'experience pro et la qualite des features V4 enriched :

| Scenario | PF cible | Trades/jour | Holding moyen | Probabilite GO |
|----------|----------|-------------|---------------|----------------|
| BREAKOUT_PULLBACK | 1.6 | 0.5 | 2h | 60% |
| RANGE_FADE | 1.4 | 1.0 | 1h | 70% |
| TREND_CONTINUATION | 1.5 | 0.3 | 3h | 50% |
| MEAN_REVERSION_SD2 | 1.5 | 0.4 | 1.5h | 65% |
| OPENING_RANGE_BREAK | 1.7 | 0.3 | 4h | 55% |

**Total attendu** : 2-3 trades/jour, PF combine 1.5-1.6 (apres deduplication).

## Risques connus

1. **Pattern 11 cascade** : 5 scenarios = 5 layers de filtres potentiels. Le market-analyst doit valider chaque scenario INDIVIDUELLEMENT avant combine.
2. **Overlap** : RANGE_FADE et MEAN_REVERSION_SD2 peuvent declencher sur les memes setups. Necessite priorite.
3. **15m bars non disponibles dans le pipeline live** : doit etre resample en temps reel cote bot.
4. **Levels MenthorQ vieillissants** : verifier que vol_model/key_levels du jour J est utilise (pas J-1).

## Decision

Si Solution B NOGO (cf bot2_ml_directional results), passer a Solution A Scenario Manager.

**Etape 1 priorite** : implementer + backtest RANGE_FADE et MEAN_REVERSION_SD2 (les 2 plus probables). Si PF >= 1.4 sur 6 mois, valider Scenario Manager. Sinon, retravailler avec Jackson sur les bases.
