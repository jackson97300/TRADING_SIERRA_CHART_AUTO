@echo off
REM Carte du matin (brique 3) - 9h25 ET = 15h25 Paris en heure d'ete (meme
REM piege DST que rythme_soir.bat : verifier la tache au 25/10 et au 1er/11).
REM Genere TOUJOURS la carte (LOGS\carte), l'affiche seulement les blocs
REM visibles du tirage en aveugle, ecrit `carte_visible` dans le journal manuel.
cd /d "%~dp0..\.."
if not exist LOGS mkdir LOGS
python -X utf8 V3\carte_matin.py >> LOGS\carte_matin.log 2>&1
