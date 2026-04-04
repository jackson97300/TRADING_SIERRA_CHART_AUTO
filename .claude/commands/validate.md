Lance la validation DMP sur les derniers fichiers JSONL collectes.

Etapes :
1. Trouve les fichiers JSONL les plus recents dans DATA/ES/ et DATA/NQ/
2. Lance `python CORE/dmp_validator.py` sur chaque fichier
3. Affiche un resume : PASS ou FAIL avec les erreurs detectees
4. Si schema != 3.7.2 ou colonnes != 262, signale immediatement

Ne modifie aucun fichier. Rapport seulement.
