Lance l'etude VWAP complete sur les donnees disponibles.

Etapes :
1. Lance `python CORE/mia_vwap_study.py DATA/ES/` puis `python CORE/mia_vwap_study.py DATA/NQ/`
2. Affiche les 9 sections : zones, mimetisme SD1-SD3, mean reversion, regime, slope filter, multi-TF, confluence, PREV VWAP, synthese
3. Compare les resultats avec l'etude precedente si disponible
4. Signale tout changement de pattern (nouveau regime = nouveaux resultats)

ATTENTION : toujours mentionner le biais de regime (baissier/haussier/neutre).
Ne modifie aucun fichier. Rapport seulement.
