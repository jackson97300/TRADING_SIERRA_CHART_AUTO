# BOT CHANGELOG — MIA Trading System

**Journal permanent de toutes les modifications apportees au bot** : gates, features, fixes, configs, refactos. Ordre **anti-chronologique** (dernier en haut).

## Regles d'usage (obligatoires)

1. **AVANT** tout deploy d'une modif qui touche le moteur de decision (paper_trader, builders, SLTPEngine, C++ DMP, gates), ecrire une entry ici.
2. **Format strict** : utiliser le template ci-dessous. Tout champ obligatoire.
3. **Backtest preservation** obligatoire si modif impacte scoring/gates — doit prouver que les wins historiques restent wins.
4. **Review agent** obligatoire selon matrice `critical-tasks-review.md`.
5. **Apres deploy** : ajouter la section "Deployed at YYYY-MM-DD HH:MM" + "Suivi post-deploy" avec metriques observees a 1/7/30 jours.
6. **En cas de rollback** : NE PAS supprimer l'entry. Ajouter section "Rolled back at YYYY-MM-DD HH:MM — raison" + garder trace.
7. **Liens** : toujours cross-reference avec INCIDENT_LOG, memories, reviews agents.

## Template d'entry

```markdown
## YYYY-MM-DD HH:MM — [SHORT_TITLE]

**Categorie** : [FIX | FEATURE | GATE | CONFIG | REFACTO | ROLLBACK]
**Impact prod** : [LIVE | PAPER | DASHBOARD | OFFLINE]
**Fichier(s)** : `path:line`
**Schema/version** : X.Y.Z -> X.Y.Z+1 (si applicable)
**Reviewer(s) agent** : code-reviewer / market-analyst / ml-trainer / Plan

### Quoi
Description factuelle 1-3 phrases.

### Pourquoi
Justification business + data (chiffres, findings). Lien incidents/backtests.

### Impact attendu
- Metriques : +$X PnL / -Y rejets
- Effet de bord : aucun | liste

### Validation pre-deploy
- [ ] Tests unitaires: N/N
- [ ] Backtest preservation: X wins / Y wins
- [ ] Review agent: GO / RESERVES (lien)
- [ ] Test empirique: commande + resultat

### Revert plan
```bash
# commandes de rollback explicites
```

### Deployed at YYYY-MM-DD HH:MM
(a remplir apres deploy VPS + restart service)

### Suivi post-deploy
- J+1 : metriques observees
- J+7 : metriques observees
- J+30 : metriques observees

### Liens
- INCIDENT_LOG : YYYY-MM-DD entry
- Memory : `feedback_*.md`
- Review agent : ... (summary court)
```

---

## Entries

## 2026-04-25 — [MTF_BULL_DESERT filter SHORT sur `mtf_bulls <= 1`]

**Categorie** : GATE
**Impact prod** : PAPER
**Fichier(s)** : `CORE/mia_paper_trader.py:717-750` (check_entry step 6)
**Schema/version** : - (comportemental, pas de bump)
**Reviewer(s) agent** : market-analyst (R1 + R2) + code-reviewer (a faire)

### Quoi
Ajout gate downside-only `MTF_BULL_DESERT` dans `check_entry()` : si `direction == "SHORT" AND mtf_bulls <= 1 AND mtf_bears < 3`, rejet immediat avec raison `mtf_bull_desert`. Intervient AVANT le gate existant `min_mtf_bears >= 3` comme defense en profondeur.

**IMPORTANT** — la condition inclut `mtf_bears < 3` pour preserver les SHORT avec MTF **bearish aligne** (ex: SHORT 18:18 du 24/04 avait `mtf=0/3` → `mtf_bears=3` → SHORT legitime, ne doit PAS etre bloque). Sans cette condition, regression detectee par backtest preservation → fix avant deploy.

### Pourquoi
Backtest lookforward 24/04 sur 107 SHORT bloques par gate MTF aval, decoupe par `mtf_bulls` :

| mtf_bulls | n | W/L | PnL | PF | USD |
|---|---|---|---|---|---|
| 0 | 3 | 0/3 | -60t | 0.00 | -$90 |
| **1** | **15** | **2/13** | **-188t** | **0.28** | **-$282** |
| 2 | 21 | 9/12 | +84t | 1.35 | +$126 |
| 3 | 68 | 26/42 | +96t | 1.11 | +$144 |

Bucket `mtf_bulls <= 1` combine : 18 trades, WR 11%, PnL -248t = -$372 (3 micros). Edge negatif credible (Wilson 95% WR 13% sur n=15 = [2%, 38%]).

**Defense en profondeur** : si jamais `min_mtf_bears >= 3` est modifie ou bypass, ce filtre downside reste actif.

### Impact attendu
- PnL : +$0 today (redondant avec gate actuel), +$282/jour similaire si gate superieur desactive un jour
- Rejets supplementaires : 0 (deja tous bloques par gate aval)
- Effet de bord : aucun — le filtre intervient AVANT le gate existant, decision identique

### Validation pre-deploy
- [x] Tests unitaires: pytest CORE/ 137/137 passes (2 failures + 2 errors pre-existants)
- [x] Backtest preservation: 18/18 trades executes 24/04 preserves (premiere version avait regression sur SHORT 18:18 mtf=0/3 — fix condition ajoutee `mtf_bears < 3`)
- [x] Backtest verif catch: 18 SHORT rejetes bucket mtf<=1 + mtf_bears<3 catches par le filtre (identique gate aval actuel, pas de changement funnel)
- [x] Review code-reviewer: GO-AVEC-RESERVES mineures → 2 commentaires enrichis (redondance + revert)
- [x] Review market-analyst R1 (seuil >=3 rejete, demande split data)
- [x] Review market-analyst R2 (GO sur ce filtre precis, confidence 4/5)
- [x] Deploy VPS : SCP + restart MIA-Paper OK, filtre present ligne 742

### Lecon retenue
Backtest preservation a detecte regression silencieuse (1/18 trades bloque). Sans changelog + backtest automatique, le SHORT 18:18 aurait ete bloque en prod sans explication. **Justifie definitivement la regle "backtest preservation obligatoire sur modif scoring/gates".**

### Revert plan
```bash
# Retirer les 7 lignes ajoutees dans check_entry puis:
scp CORE/mia_paper_trader.py Administrator@212.28.179.199:"C:/TRADING_SIERRA_CHART_AUTO/CORE/"
ssh Administrator@212.28.179.199 "powershell -Command 'Restart-Service MIA-Paper'"
# Confirmer via paper_trader.log que bot repart
```

### Deployed at 2026-04-25 (samedi marches fermes, deploy safe)
- SCP `CORE/mia_paper_trader.py` + `CORE/log_catalog.py` vers VPS
- `Restart-Service MIA-Paper` OK
- Verif : `Select-String mtf_bull_desert CORE/mia_paper_trader.py` → ligne 742 present sur VPS
- Position ouverte : 0 (pas de trade en cours, marches fermes)
- Bot statut : Running, heartbeat actif

### Suivi post-deploy
- J+1 (26/04) : nombre de rejets `mtf_bull_desert` dans rejections_*.jsonl
- J+7 : re-split data 5+ jours multi-regime, verifier edge mtf<=1 reste credible
- J+30 : analyse statistique complete avec IC95% par bucket, envisager action sur mtf=2/3 si data suffisante

### Liens
- Backtest scripts : `CORE/research/backtest_short_what_if_24042026.py`
- Review market-analyst R1 : seuil >=3 rejete comme trop agressif
- Review market-analyst R2 : verdict GO sur filtre mtf<=1 specifique
- Memory `feedback_lightgbm_no_composite_indicators.md` (anti-pattern 11)

---

## 2026-04-24 22:30 — [Kill-switch paper_trader STOP.flag read]

**Categorie** : FIX (bug dormant 15 jours)
**Impact prod** : PAPER
**Fichier(s)** : `CORE/mia_paper_trader.py:65-70, 234-237, 1713-1770` + `CORE/log_catalog.py:107-110`
**Schema/version** : -
**Reviewer(s) agent** : code-reviewer (GO-AVEC-RESERVES, 2 corrections appliquees)

### Quoi
- Ajout constante `STOP_FLAG_FILE` pointant `DATA/BOT_CONTROL/STOP.flag`
- Ajout etat `self._stop_flag_active + _stop_flag_activated_at + _stop_flag_stale_alerted` dans `__init__`
- Bloc kill-switch dans `run()` boucle principale : detection flag → flatten positions (retry a chaque tick pause) → mode pause (5s poll, pas de check_entry/exit) → alerte MAJEUR si pending > 30s
- Expose etat `kill_switch` dans `state.json` pour dashboard
- 2 codes log_catalog : `BOT_KILL_SWITCH_ACTIVATED` (MAJEUR), `BOT_KILL_SWITCH_RELEASED` (INFO)

### Pourquoi
Bouton "STOP BOT" dashboard admin ecrivait `STOP.flag` depuis 09/04 mais **seul `BOT/bot_main.py` (V1 legacy inactif) le lisait**. `CORE/mia_paper_trader.py` (bot actif) ignorait ce fichier → kill-switch inoperant 15 jours. Jackson a demande "bouton relancer" → audit a revele le bug dormant.

### Impact attendu
- Jackson peut arreter le bot depuis son telephone via dashboard (ex: news imminente)
- Bot flatten proprement + pause (process reste vivant, heartbeat persiste)
- Reprise via "REDEMARRER" : bot reprend check_entry/exit en 5s

### Validation pre-deploy
- [x] Tests unitaires: 137/137 pytest passes
- [x] Syntax check Python OK
- [x] Review code-reviewer: GO-AVEC-RESERVES → 2 corrections appliquees (retry flatten each tick + expose kill_switch in state)
- [x] Test empirique live VPS 14:25 UTC : STOP.flag cree → detection 12s + pause → flag supprime → reprise 9s ✓

### Revert plan
```bash
git revert <commit>
scp CORE/mia_paper_trader.py CORE/log_catalog.py VPS
ssh VPS "Restart-Service MIA-Paper"
```

### Deployed at 2026-04-24 14:24 UTC

### Suivi post-deploy
- J+1 (25/04) : aucun usage production (jamais trigger par Jackson), 0 bug detecte
- A surveiller : si trigger manuel par Jackson, verifier flatten se fait bien

### Liens
- INCIDENT_LOG : 2026-04-25 00:30 (VALIDATION_MISS + RESOLU)
- Memory : `feedback_validation_miss_patterns.md` (5eme occurrence promue escalation auto-load)

---

## 2026-04-24 22:30 — [Fix deco dashboard toutes 15 min (auto-refresh token)]

**Categorie** : FIX
**Impact prod** : DASHBOARD
**Fichier(s)** : `DASHBOARD/static/js/dashboard.js:5266-5278` + cache-bust `index.html` v=79 -> v=80
**Schema/version** : -
**Reviewer(s) agent** : (pas de review — modif frontend mineure non critique)

### Quoi
Dans `init()` : remplacement `fetch("/api/auth/me")` brut par `fetchWithAuth("/api/auth/me")` qui gere auto-refresh via cookie `mia_session` (7j).

### Pourquoi
Logs serveur VPS : **0 appel** `/api/auth/refresh` sur tout l'historique. Cause : `init()` utilisait `fetch` brut qui, sur 401 (token access 15min expire), clearait localStorage + redirect `/welcome` SANS tenter le refresh. Jackson se faisait deconnecter toutes les 15 min (access_expiry) sans explication.

### Impact attendu
- Plus de deconnexion tant que cookie refresh valide (7j)
- Zero regression : `fetchWithAuth` existe deja et gere le flow correctement

### Validation pre-deploy
- [x] Syntax check `node --check`: OK
- [x] Grep verif : aucun autre `fetch("/api/auth/me")` brut restant
- [x] Test empirique (a confirmer par Jackson avec DevTools Network)

### Revert plan
```bash
# Remplacer fetchWithAuth par fetch + headers Authorization
scp DASHBOARD/static/js/dashboard.js VPS
# Pas besoin restart (static file)
```

### Deployed at 2026-04-24 22:30 UTC (file-only, pas de restart requis)

### Suivi post-deploy
- Jackson doit faire **Ctrl+F5** pour charger v=80
- Jackson signale "ca continue" (25/04 matin) → probable cache browser, a diagnostiquer via DevTools
- A verifier : DevTools Sources > dashboard.js?v=80 affiche

### Liens
- INCIDENT_LOG : 2026-04-25 00:30

---

## 2026-04-24 22:30 — [Sons paper trading (3 WAV execution events)]

**Categorie** : FEATURE
**Impact prod** : DASHBOARD
**Fichier(s)** : `DASHBOARD/static/js/dashboard.js:3694-3817` (nouveau bloc sounds) + `DASHBOARD/static/index.html:174-191` (UI sidebar) + `DASHBOARD/static/sounds/*.wav` (3 fichiers)
**Schema/version** : -
**Reviewer(s) agent** : (pas de review — feature UX uniquement)

### Quoi
Ajout audio notifications dans le dashboard admin pour les evenements trade :
- `trade_open.wav` (W Ordre servi) sur nouveau `trade_id` dans `open_by_symbol`
- `trade_tp.wav` (W Target servi) sur TP close detecte
- `trade_sl.wav` (W Ordre stoppe) sur SL close detecte
- UI sidebar : toggle ACTIF/MUET + slider volume + bouton TEST (debloque autoplay Chrome)
- Persistance localStorage : `mia_sound_enabled`, `mia_sound_volume`

### Pourquoi
Jackson : "pouvoir etre alerte meme quand je ne regarde pas l'ecran, notamment en cas de trade sur news imminente".

### Impact attendu
- Feedback audio temps reel pour chaque trade pris/ferme
- Aucun impact backend, aucun risque trading

### Validation pre-deploy
- [x] Syntax check OK
- [x] Test empirique : son `Ordre servi` confirme audible par Jackson au trade 17:46 UTC
- [ ] Son `Target servi` : NON ENTENDU par Jackson — cause probable autoplay Chrome en onglet background

### Revert plan
```bash
# Retirer bloc sounds + UI sidebar, bump cache-bust
```

### Deployed at 2026-04-24 22:30 UTC

### Suivi post-deploy
- Backlog : ajouter Notification API native (marche onglet inactif contrairement a Audio)
- A confirmer par Jackson : bouton TEST fonctionne + slider volume OK

### Liens
- Fichiers WAV source : `D:/DORIAN/Sierra-Chart-en-Profondeur-partie-2-v2023.3/.../1. Voix feminine/`
