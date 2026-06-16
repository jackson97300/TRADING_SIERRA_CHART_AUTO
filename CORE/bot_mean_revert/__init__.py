"""Bot Mean Revert VWAP (Sim1) - mean reversion sur extensions SD bands.

Edge ES sweep v2 (Jackson 16/06/2026) :
  - Config : SD3 + RR 1.5 + US-only + slope_30>0 + skip London + skip pre-open 11:30-13:30 UTC
  - Performance : PF 1.69 sur 70 trades / +$520 sur 4 jours.

NQ : dry-evaluate Asia (logge hypothetical, decision data-driven J+14).

Architecture reuse Bot 1 v2 :
  - DailyLimitsGate, SessionGate, SierraDataSource, PositionStore, OrderRouter
  - StateBridge (sub-class : state_sim1.json)
  - Codes catalog BOTMR_* dedies (17 codes, voir CORE/log_catalog.py)
"""
