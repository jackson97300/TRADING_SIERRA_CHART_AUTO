@echo off
cd /d C:\TRADING_SIERRA_CHART_AUTO
echo === Rebuild NQ 14 mois Phase B avec regime z-score fix === > LOGS\rebuild_nq_zscore.log
for %%m in (2025-04 2025-05 2025-06 2025-07 2025-08 2025-09 2025-10 2025-11 2025-12 2026-01 2026-02 2026-03 2026-04 2026-05) do (
  echo === NQ Month %%m === >> LOGS\rebuild_nq_zscore.log
  python -X utf8 -m CORE.build_dataset_v4_phase_b --month %%m --symbols NQ --no-intermarket >> LOGS\rebuild_nq_zscore.log 2>&1
)
echo === ALL_DONE NQ === >> LOGS\rebuild_nq_zscore.log
echo === Concat NQ dataset === >> LOGS\rebuild_nq_zscore.log
python -X utf8 concat_nq_dataset.py >> LOGS\rebuild_nq_zscore.log 2>&1
echo === ALL_DONE === >> LOGS\rebuild_nq_zscore.log
