# PLAN OPÉRATIONNEL — de l'observateur au bot (audit Fable 09/09)

*Fable, sur le miroir à `b46f6db`. Question : indépendamment des couches, que
faut-il coder pour que le système passe des ordres, se lance, survive, se
voie ? Constat en une ligne : **le dépôt contient un observateur complet et
zéro exécuteur** — aucun `SubmitOrder`, aucun bracket, aucun OCO. Le bot sait
ce qu'il ferait ; il n'a pas de mains. Conforme au plan (ombre = observation),
et c'est le point exact où « trader lundi » bute.*

## Inventaire par brique

| brique | état | manque |
|---|---|---|
| Lecture/décision (L0→L5) | EXISTE | rien — scellé/observé comme prévu |
| Coureur live + garde | EXISTE | garde-du-garde **CONFIRMÉ** (tâches 5 min sur les 2 machines, vérifié 10/09) |
| Sync VPS | EXISTE | retry `PermissionError` — **FAIT 10/09** |
| Rythme du soir (6 étapes) | EXISTE | `.tmp`+`os.replace` — **FAIT 10/09** |
| Barrières (sortie) | PARTIEL | B-BOUEE ; **les ombres n'ont aucune barrière** (9/9 signaux du jour 1) |
| **EXEC — passer un ordre** | **ABSENT** | tout (§EXEC) |
| Lanceur | PARTIEL | `launch.py` mince, 30 lignes, aucune logique |
| Portes prop firm | ABSENT | `pnl_jour`/`fin_cooldown` câblés depuis EXEC ; PF_DRAWDOWN_TRAILING, PF_CONSISTANCE observées ; `config/propfirm.yaml` |
| État de position | PARTIEL | l'état ÉCRIT par EXEC (`LOGS/execution/etat_<sym>.json`) — ce que L0 lit et ne trouve pas |
| Vitrine/Discord | ABSENT | panneau lecture seule, jamais le P&L — semaine du 21 |
| Kill switch | ~~ABSENT~~ | **FAIT 10/09** : fichier `STOP` à la racine — coureur s'arrête au cycle, garde tue et ne relance JAMAIS tant qu'il est là |
| Sauvegarde dépôt principal | ABSENT | webhooks Discord — **161 commits sans copie distante, 6e jour** |

## EXEC — spécifié pour lundi (SIM uniquement, < 300 l. + faux DTC)

1. Lit les signaux **retenus** de l'entonnoir — jamais les ombres, jamais un bloqué.
2. Ordre marché à l'open de t+1, 1 micro, sens du signal.
3. Bracket OCO depuis `barrieres.py` — B-ATR (SL 1,0 / TP 1,5 ATR-15m), points→ticks par `TICK`, jamais en dur.
4. Règles DTC de janvier RECOPIÉES : `OrderStatus 7` = seul fill ; cancel par `ServerOrderID` ; orphelins nettoyés au boot ; un ordre en vol par instrument (lock 5 s) ; reconnexion backoff.
5. **Plat à 15h55 ET** (sortie `EOD` distincte de TP/SL), jamais d'overnight.
6. Contrat = `calendrier.contrat_actif()` vérifié contre le fichier.
7. **Écrit l'état** que L0 lit → les trois portes stop/cooldown cessent d'être inertes.
8. Journal `LOGS/execution/exec_<jour>.jsonl`, lié par `snapshot_id`, un seul écrivain.

Mesures dès le jour 1 (la raison d'exister d'EXEC pendant l'ombre) :
`glissement_reel` (fill − open t+1, en ATR), latence signal→fill, part des TP
« au tick » (fills SIM optimistes).

Tests non négociables avant le premier ordre : fill partiel, rejet,
déconnexion en plein bracket, doublon à la relance, rollover entre deux
ordres, L0 strict bloque avant EXEC, kill switch → plat. **Sur le VPS, avec
l'exécutable de la tâche** (`exe` du battement) — la leçon du 08/09.

## Ordre de construction

| quand | quoi |
|---|---|
| **jeudi 10** | rollover (décision jour J) ; ~~.tmp+replace~~ ✔ ; ~~retry~~ ✔ ; ~~kill switch~~ ✔ ; `EOD_LOCKOUT` sur `minutes_et` |
| **vendredi 11** | **B-ATR sur les ombres** ; `config/propfirm.yaml` + portes PF observées ; GEL de la chaîne |
| **lundi 14-mardi 15** | `exec_sim.py` + faux DTC + tests ; état écrit ; `pnl_jour`/`fin_cooldown` câblés |
| **mercredi 16** | tests VPS avec l'exe de la tâche ; `launch.py` ; premier ordre SIM **Jackson devant l'écran** |
| **jeudi 17 →** | 20 jours d'exécution SIM ; glissement mesuré ; B-BOUEE (MAE des gagnants) |
| **semaine du 21** | vitrine + Discord (machine ≠ pont DTC) |

## Ce que ce plan ne dit pas

Il ne dit pas que le bot gagnera — c'est le jour 61. Il dit que la distance
est de quatre briques dont une seule est grosse (EXEC), et que la seule chose
qui manque à toutes est la même depuis une semaine : **une sauvegarde
distante du dépôt principal**. Le premier ordre SIM sur un projet sans
sauvegarde est un ordre passé sur un projet qui peut disparaître le même jour.
