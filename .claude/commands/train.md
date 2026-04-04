Lance le pipeline complet : DatasetBuilder v2 + Training LightGBM.

Etapes :
1. Lance `python CORE/dataset_builder.py --current` pour rebuilder les datasets avec features derivees
2. Affiche le screening Spearman (features validees ES et NQ)
3. Lance `python CORE/train_lightgbm.py` pour entrainer les 4 modeles (ES buy, ES sell, NQ buy, NQ sell)
4. Affiche le rapport GO/NO-GO avec metriques de trading (PF, WR, EV, Sharpe)
5. Sauvegarde les modeles dans DATA/MODELS/

Prerequis : minimum 15 jours de donnees propres dans DATA/ES/ et DATA/NQ/
