Synchronise les donnees JSONL depuis le VPS vers le PC local.

Connexion : ssh Administrator@212.28.179.199

Etapes :
1. Lister les fichiers JSONL sur le VPS dans C:\TRADING_SIERRA_CHART_AUTO\DATA\ES\ et NQ\
2. Comparer avec les fichiers locaux dans D:\TRADING_SIERRA_CHART_AUTO\DATA\ES\ et NQ\
3. Copier les fichiers manquants ou plus recents via scp
4. Afficher un resume : fichiers copies, nombre de barres par fichier
5. Lancer automatiquement la validation (dmp_validator.py) sur les nouveaux fichiers

Ne modifie aucun fichier sur le VPS. Lecture seule cote VPS.
