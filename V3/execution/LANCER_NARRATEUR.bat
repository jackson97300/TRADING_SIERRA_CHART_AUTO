@echo off
rem ===========================================================================
rem  LANCER LE NARRATEUR - le module SCENARIOS, visible dans ce terminal.
rem
rem  Double-clic, ou depuis un terminal. Il demarre ce qui MANQUE et rien
rem  d'autre : si un ecrivain tourne deja, il ne demarre PAS le second (c'est
rem  l'incident du 08/09 - deux ecrivains, et plus aucun journal qui fasse foi).
rem
rem  Fermer cette fenetre (Ctrl-C) ne tue ni l'ecrivain ni la vitrine : ils sont
rem  detaches, la campagne ne s'arrete pas parce qu'on ferme un moniteur.
rem
rem  Options, a ajouter apres le nom du script si besoin :
rem     --sans-fenetre   ne pas ouvrir la fenetre epinglee
rem     --une-fois       afficher l'etat une seule fois, puis rendre la main
rem
rem  Chemins relatifs a ce fichier (%~dp0 = son dossier, deux crans au-dessus =
rem  la racine du depot) : aucun chemin de machine ici.
rem ===========================================================================
chcp 65001 >nul
title Narrateur de seance - MIA V3
cd /d "%~dp0..\.."
if not exist LOGS mkdir LOGS
python -X utf8 -u V3\execution\lanceur.py %*
echo.
echo   Le moniteur est ferme. L'ecrivain et la vitrine continuent.
pause
