BASELINE DEAD FEATURES — 2026-06-15T15:50:38Z

Reference snapshot AVANT corrections bugs identifies par audit 4 agents.

## Stats reference

NQ 4 jours (10-15/06, 15169 bars) : DEAD=157 ALIVE=474 (24.9% DEAD)
ES 5 jours (10-15/06, 11762 bars) : DEAD=160 ALIVE=471 (25.4% DEAD)

## Fichiers

- feature_catalog_v5_baseline.csv : 613 features × 12 metadata cols
- feature_catalog_v5_baseline.json : structure JSON par famille -> sous-famille
- dead_filter_NQ_4j_baseline.csv : 631 features avec status DEAD/ALIVE + reasons
- dead_filter_ES_5j_baseline.csv : idem ES

## Bugs cibles (cf DOCS/AUDIT_DEAD_FEATURES_20260615.md)

| Bug | Statut baseline | Statut cible apres fix |
|-----|------------------|------------------------|
| #1 cvd_day_dir NQ | CONSTANT 1 (100%) | Distribution +1/0/-1 ~50/15/35% |
| #2 delta_div_*_clean | CONSTANT 0 (4 features, 0% fire rate) | Fire rate 5-40% du raw |
| #3 composite_poc_5d/20d | NULL 100% | < 5% NULL apres J+5 trading days |
| #4 dist_blind_nearest_up/dn | NULL 100% | < 20% NULL |
| #5 dist_color_*_pct | NULL 99% NQ | < 60% NULL |
| #6 bool_va_confluence | CONSTANT 0 (100%) | > 10% top=1 |

## Workflow comparaison

Apres tous fixes deployes :
1. Sync VPS->local nouveau JSONL multi-jours
2. Run feature_catalog_v5 + dead_filter sur nouveaux JSONL
3. Comparer csv post-fix vs csv baseline (diff features status DEAD->ALIVE)
4. Tracker dans bilan final DOCS/AUDIT_DEAD_FEATURES_RESOLUTION_20260620.md

## Rules

- NE PAS modifier ces fichiers baseline (read-only reference)
- Date snapshot fige dans le nom du dossier
- INCIDENT_LOG entries #57-#60 cross-reference cette baseline
