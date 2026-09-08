@echo off
REM Le rythme du soir, lance par la tache planifiee MIA-V3-RythmeSoir a 23:01
REM LOCALE (= 21:01 UTC EN HEURE D'ETE SEULEMENT). Au changement d'heure
REM europeen du 25/10/2026 — en pleine campagne — il faut passer la tache a
REM 22:01 locale ; rythme_soir.py REFUSE de tourner hors de la fenetre UTC
REM attendue plutot que de mesurer la mauvaise journee en silence.
REM %~dp0 = le dossier de ce script ; deux crans au-dessus = la racine du
REM depot. Aucun chemin de machine ici : V3/ est miroite en public.
cd /d "%~dp0..\.."
if not exist LOGS mkdir LOGS
python -X utf8 V3\execution\rythme_soir.py >> LOGS\rythme_soir.log 2>&1
