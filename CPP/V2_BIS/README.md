# V2_BIS — Bot C++ ACSIL natif Sierra Chart

**Statut** : DRAFT P0 squelettes (pre-work P1 autorise en S5, gate P0→P1 = fin mai V2CLEAN shadow stable)

**Design complet** : `DOCS/V2_BIS_DESIGN_P0.md` v1.4.1 (GO SANS RESERVE)

## Principe

```
V2CLEAN Python (CERVEAU)  ────► JSONL signal  ────►  V2-bis C++ (BRAS)
  - ML LightGBM                                        - Lit signal (file watch)
  - Meta-labeling Lopez                                - OCO native ACSIL
  - PSR/DSR validation                                 - Risk + kill-switch
                                                       - Snapshot ML V3-ready
```

**V2-bis EXECUTE, NE DECIDE PAS.** Pattern 11 V1 reborn = interdit.

## Architecture 13 modules (~3390 LOC)

```
V2_BIS/
├── V2_Main.cpp              (~200)  dispatcher ACSIL + chain of gates
├── V2_JSONLBridge.h         (~280)  file watch ml_signal.jsonl + dedup + heartbeat
├── V2_OrderExec.h           (~450)  OCO + Trailing + BE + Smart entry
├── V2_RiskManager.h         (~450)  port risk_manager.py (716 LOC)
├── V2_Config.h              (~100)  config centralisee
├── V2_StatePersistence.h    (~120)  atomic I/O + corruption recovery
├── V2_HealthCheck.h         (~80)   heartbeat + staleness V2CLEAN
├── V2_EventJournal.h        (~80)   tracer evenements structures
├── V2_SnapshotWriter.h      (~280)  JSONL append ML V3-ready
├── V2_SessionGuard.h        (~120)  London + US + pause OPR (time-based PUR)
├── V2_Interfaces.h          (~280)  DI : 9 interfaces
├── V2_MockImpl.h            (~350)  mocks tests Catch2
└── V2_Tests.cpp             (~600)  79 tests (unit + integration + statiques pattern 11)
```

## Status fichiers actuels

Tous les .h/.cpp = **squelettes stubs** (signatures + types, **zero logique metier**).

Implementation reelle demarre **apres gate P0→P1** (V2CLEAN shadow stable 7j, cible fin mai).

## Gates

- **P0→P1** : V2CLEAN shadow mode stable 7j (cible debut juin 2026)
- **P4→P5** : V2CLEAN paper GO + V2-bis **100 trades clean** (cible juillet)

## Gardes-fous pattern 11 (design section 8)

5 regles + 4 criteres testables + 4 tests statiques CI (grep no-score-branching).
`V2_RiskManager.allow_trade()` recoit `RiskSignal` (pas `Signal`) → compilateur empeche lecture `score_*`.
