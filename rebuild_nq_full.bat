@echo off
cd /d C:\TRADING_SIERRA_CHART_AUTO
echo === Rebuild NQ Phase A + Phase B 14 mois (z-score regime) === > LOGS\rebuild_nq_full.log
echo === Phase A NQ : Databento + MQ ingest 14 mois === >> LOGS\rebuild_nq_full.log
python -X utf8 -m CORE.build_dataset_v4_dmp_databento --symbols NQ --start 2025-04-01 --end 2026-05-15 --use-mq-lite >> LOGS\rebuild_nq_full.log 2>&1
echo === Phase B NQ : 14 mois === >> LOGS\rebuild_nq_full.log
for %%m in (2025-04 2025-05 2025-06 2025-07 2025-08 2025-09 2025-10 2025-11 2025-12 2026-01 2026-02 2026-03 2026-04 2026-05) do (
  echo === NQ Month %%m === >> LOGS\rebuild_nq_full.log
  python -X utf8 -m CORE.build_dataset_v4_phase_b --month %%m --symbols NQ --no-intermarket >> LOGS\rebuild_nq_full.log 2>&1
)
echo === ALL_DONE NQ === >> LOGS\rebuild_nq_full.log
echo === Concat NQ_dataset_v5e_clean === >> LOGS\rebuild_nq_full.log
python -X utf8 concat_nq_dataset.py >> LOGS\rebuild_nq_full.log 2>&1
echo === ALL_DONE === >> LOGS\rebuild_nq_full.log
