# Sierra Live IO Parity Report — NQ

**Date generation** : 2026-06-06
**Symbol** : NQ
**Jours testes** : 10 (20260514 -> 20260603)

## Resume

- Signed-critical features parite : **100/100** = **100.0%**
- Additional numeric parite : **230/230** = **100.0%**
- CVD sign coherent direction marche (proxy garde-fou Phase 1.6) : **7/10** = **70.0%**

**VERDICT** :
- ✅ Signed-critical : 100% parite (GO migration)
- ⚠️ Garde-fou signe : 70% < 80% (investiguer)

## Detail par jour

| Day | Bars (raw/reader) | Signed-Critical MATCH | Direction | CVD end | Signe coherent |
|---|---|---|---|---|---|
| 20260514 | 1380/1380 | 10/10 | HAUSSIER (166.0 pts) | -1665 | WARN |
| 20260515 | 1379/1379 | 10/10 | BAISSIER (-533.5 pts) | -2338 | OK |
| 20260517 | 1/1 | 10/10 | - (- pts) | -2089 | WARN |
| 20260518 | 1379/1379 | 10/10 | BAISSIER (-94.2 pts) | -3961 | OK |
| 20260519 | 597/597 | 10/10 | RANGE (3.8 pts) | -3255 | OK |
| 20260520 | 1380/1380 | 10/10 | HAUSSIER (345.5 pts) | 6750 | OK |
| 20260521 | 1380/1380 | 10/10 | HAUSSIER (220.2 pts) | 2500 | OK |
| 20260522 | 46/46 | 10/10 | HAUSSIER (39.8 pts) | 2920 | OK |
| 20260602 | 1380/1380 | 10/10 | HAUSSIER (229.2 pts) | -4888 | WARN |
| 20260603 | 980/980 | 10/10 | RANGE (-19.5 pts) | -5583 | OK |
