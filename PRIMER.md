# PRIMER — MIA Trading System
> Derniere MAJ: 02/04/2026 | Lire CLAUDE.md pour le detail technique

## Etat actuel
- Bot H24 sur VPS (Sim3 paper) — ES seulement, Task Scheduler `MIA_BOT`
- **347 features** : DMP 264 + ctx 36 + im 10 + mq 37
- **7 jours** de collecte (27/03 → 02/04), objectif 15 jours pour ML
- RuleEngine actif mais faible (2 trades, 2 losses) — ML le remplacera
- DTC bracket valide (OCO manuel + ServerOrderID)
- MenthorQ scraper : 98 slugs, 2x/jour automatique

## Pipeline fonctionnel
```
Sierra Chart C++ → JSONL 262 cols/barre/min
  + MenthorQ JSON → 37 features daily (scraper)
  + Rolling Python → 36 features (ctx_*)
  + Intermarket → 10 features (im_*)
  = 347 features → RuleEngine (maintenant) ou LightGBM (bientot)
  → DTC → Sierra Chart → AMP broker (Sim3)
```

## Prochaines etapes (dans l'ordre)
1. **Collecte** — continuer jusqu'au 8 avril minimum
2. **Training ML** — LightGBM walk-forward, 2 modeles (buy+sell) par instrument
3. **Rolling retraining** — hebdomadaire, JAMAIS figer le modele
4. **Modeles par regime** — VIX < 20 vs VIX > 25

## Decisions prises (ne pas revenir dessus)
- OCO manuel obligatoire (Type 206 / OCOGroup1 ne marchent PAS)
- Cancel avec ServerOrderID (sans = ignore par SC)
- OrderStatus 7 = Filled (PAS 2)
- JSONL le plus recemment modifie (pas par nom — date session != date systeme)
- pythonw.exe ou Task Scheduler pour process persistant sur VPS Windows
- Session H24 (Asia + London + US)
- Max 10 trades/jour, cooldown 10 barres

## Ce qui ne marche PAS
- RuleEngine IF/ELSE — trop simpliste, trades de debutant
- Type 206 / IsParentOrder — SC serveur DTC les ignore
- DTC market data — SC refuse, fallback prix via JSONL
- CTA/Vol Models via API MenthorQ — endpoints 403, pas dispo via AJAX
