@echo off
REM Rythme du soir ? 23:01 locale = 21:01 UTC en heure d'ete. Voir la
REM docstring de rythme_soir.py (piege DST du 25/10, en pleine campagne).
REM %~dp0 = dossier du script ; deux crans au-dessus = racine du depot.
cd /d "%~dp0..\.."
if not exist LOGS mkdir LOGS
python -X utf8 V3\execution\rythme_soir.py >> LOGS\rythme_soir.log 2>&1
