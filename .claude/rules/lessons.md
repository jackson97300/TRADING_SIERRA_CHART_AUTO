# Lecons apprises (ne pas refaire ces erreurs)

## DTC
- OrderStatus=2 n'est PAS Filled → le bot envoyait des brackets sur des ordres non-remplis
- Cancel sans ServerOrderID est IGNORE silencieusement par Sierra Chart
- Type 206, IsParentOrder, OCOGroup1 sont MORTS en mode SC serveur DTC
- pythonw.exe ou Task Scheduler pour process persistant — python.exe detache meurt

## Bot
- Position fantome : quand SL/TP fill via OCO, retirer la position du tracking
- JSONL : utiliser `max(st_mtime)` pas tri par nom (date session != date systeme)
- Gamma hardcode a 0.0 = gate MenthorQ jamais actif → lire depuis features mq_*
- DTC market data refuse par SC → fallback prix via derniere barre JSONL

## RuleEngine
- IF/ELSE ne capture pas la complexite du marche → attendre le ML
- VA basse en trend baissier != BUY (c'est un breakdown)
- BN color up=1 ET dn=1 = neutre, pas confirmation
- HVN a 10t au-dessus = MUR, ne pas acheter
- Momentum filter obligatoire : bloquer BUY si slope < -0.3 ET delta < -10K

## ML
- 3 jours de donnees = insuffisant pour des regles fiables
- 90-100% WR sur 15 trades = pas significatif statistiquement
- Rolling retraining hebdomadaire = technique #1 des fonds quant
- Overfitting sur backtest = risque #1

## Pipeline
- Le bench necessite `DATA/ES DATA/NQ` en 2 arguments (pas 1 dossier DATA)
- Le scraper MenthorQ MidDay doit forcer --today (sinon prend la veille)
- CTA et Vol Models MenthorQ : API 403, endpoints non disponibles via AJAX
