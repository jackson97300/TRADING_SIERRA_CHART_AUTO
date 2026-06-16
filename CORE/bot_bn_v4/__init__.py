"""Bot BN V4 (Sim3) — Reincarnation Bataille Navale V4 sur sierra_enriched.

Reprise du moteur pur CORE.bn_v4_engine (PF 4.66 NQ A++ Jackson 23/05/2026)
avec orchestrateur live calque sur Bot 1 v2 (CORE.bot1_v2.main pattern).

Architecture :
  config.py         : BotBNV4Config (env overridable)
  sierra_compat.py  : reconstruit 5 features absentes en sierra_enriched
  signal_engine.py  : wrap BNV4Engine + deque(500) rolling window
  trailing.py       : Dow pivots SL trail (active position)
  gates/regime.py   : trend recent baissier + density A++ + edge buy gates
  execution/order_router.py : DTC ClientName=MIA_BotBN, TradeAccount=Sim3
  main.py           : orchestrateur poll loop

Logging : codes catalog BOTBN_* + JSONL dedie LOGS/bot_bn_v4_decisions/.

Usage :
    python -m CORE.bot_bn_v4.main --symbols NQ --dry-run --verbose

Jackson 16/06/2026 : Sim3 libre depuis kill Bot 3 v3 + MP.
"""
