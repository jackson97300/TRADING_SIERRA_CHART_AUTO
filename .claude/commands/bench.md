Lance le benchmark mia_bench.py sur les donnees du jour.

Etapes :
1. Identifie les fichiers JSONL les plus recents dans DATA/ES/ et DATA/NQ/
2. Lance `python CORE/mia_bench.py DATA/ES/` puis `python CORE/mia_bench.py DATA/NQ/`
3. Affiche le resume du rapport (tests passes/echoues, features ranking)
4. Signale tout test FAIL ou regression par rapport au schema 3.7.2

Ne modifie aucun fichier. Rapport seulement.
