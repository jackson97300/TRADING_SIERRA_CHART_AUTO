Lance un audit qualite complet des features du dataset V2.

Etapes :

1. **Validator code-level** (rapide, ~5s)
   Lance `python -X utf8 CORE/quality_validator.py --no-strict` sur les datasets existants (DATA/DATASETS/ES_dataset_v2.parquet, NQ_dataset_v2.parquet) et affiche le rapport RED/YELLOW/GREEN.

2. **Verdict synthetique**
   - Si 0 red flag : afficher "PASSED — dataset propre, pret pour training"
   - Si red flags detectes :
     - Afficher la liste groupee par type de violation (INSTRUMENT / VOLATILITY / PRICE_LEVEL / OUTLIER / CONSTANT)
     - Proposer le plan de fix : DROP, NORMALIZE, ou EXEMPTION
     - Indiquer combien de features resteraient apres nettoyage

3. **Option deep** (si user ajoute `deep` en argument)
   Lance en parallele 4 subagents feature-engineer pour audit approfondi par groupe :
   - Agent 1 : DMP core features (hors prefixes ctx_/im_/amd_/rvol_/mq_)
   - Agent 2 : `ctx_*` (rolling features)
   - Agent 3 : `amd_*` + `rvol_*` + `im_*`
   - Agent 4 : `mq_*` (MenthorQ)
   Chaque agent retourne RED/YELLOW/GREEN + code source + fix suggere.

4. **Rapport final**
   Affiche un tableau consolide :
   | Scope | Audites | RED | YELLOW | GREEN | Action |

Rappel regles (`.claude/rules/data-quality.md`) :
- Qualite > symetrie ES/NQ > screening Spearman
- Une feature polluee doit etre droppee des 2 datasets
- Mieux vaut 100 features propres que 129 avec 4 fuites
- Ne jamais valider un dataset sur sa FORME uniquement

Ne modifie AUCUN fichier. Rapport seulement.

Utilisation :
- `/audit-features` — audit rapide (validator.py seul)
- `/audit-features deep` — audit approfondi (4 subagents en parallele, ~5min)
