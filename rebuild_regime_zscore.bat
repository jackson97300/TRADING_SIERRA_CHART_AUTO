@echo off
cd /d C:\TRADING_SIERRA_CHART_AUTO
echo === Rebuild ES + MGC apres regime_engine fix z-score === > LOGS\rebuild_regime_zscore.log
echo === Rebuild ES 12 mois Phase B === >> LOGS\rebuild_regime_zscore.log
for %%m in (2025-04 2025-05 2025-06 2025-07 2025-08 2025-09 2025-10 2025-11 2025-12 2026-01 2026-02 2026-03 2026-04 2026-05) do (
  echo === ES Month %%m === >> LOGS\rebuild_regime_zscore.log
  python -X utf8 -m CORE.build_dataset_v4_phase_b --month %%m --symbols ES --no-intermarket >> LOGS\rebuild_regime_zscore.log 2>&1
)
echo === Rebuild MGC 12 mois Phase B === >> LOGS\rebuild_regime_zscore.log
for %%m in (2025-05 2025-06 2025-07 2025-08 2025-09 2025-10 2025-11 2025-12 2026-01 2026-02 2026-03 2026-04) do (
  echo === MGC Month %%m === >> LOGS\rebuild_regime_zscore.log
  python -X utf8 -m CORE.build_dataset_v4_phase_b --month %%m --symbols MGC >> LOGS\rebuild_regime_zscore.log 2>&1
)
echo === ALL_DONE === >> LOGS\rebuild_regime_zscore.log
