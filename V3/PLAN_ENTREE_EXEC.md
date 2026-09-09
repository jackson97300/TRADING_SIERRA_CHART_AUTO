# LES RÈGLES D'ENTRÉE — du signal retenu à l'ordre

*Spec Fable 09/09 (sur `chaine.appliquer`, `_ouvrir`, `coureur_live.cycle` à
`b46f6db`), vérifiée au code par Claude, avec deux corrections marquées
[AJOUT]. NON CODÉE — c'est le plan de lundi (après le gel de vendredi).
Trois bots sont morts parce que décision et exécution ne partageaient pas le
même état. V3 a une décision propre et zéro exécution ; ceci est le point de
jonction, et le code actuel a un défaut à cet endroit précis.*

## 0. Le défaut, confirmé au code (chaine.py:165-167)

`L0_POSITION_OUVERTE` est alimentée par `_ouvrir()`, qui appelle
`triple_barriere(df, i, side)` **sur le futur** :

    r = triple_barriere(df, i, side, ...)   # cherche TP/SL APRÈS i
    if r is None:
        etat.update(libre_a=-1, ...)        # pas de sortie -> libre_a = -1

Hors ligne le futur existe : `libre_a` = la barre de sortie, la porte ferme
tout ce qui arrive avant. **En live le futur n'existe pas encore** : à 11h00
la barrière du trade de 10h45 n'est pas touchée, `triple_barriere` rend
`None`, `libre_a = -1`, et `i <= libre_a` ne bloque plus rien. Un second
signal PASSE alors qu'une position est ouverte ; au cycle suivant, la sortie
connue re-bloque rétroactivement le second, mais sa ligne PASSE est déjà
écrite. **Deux PASSE simultanés, un verdict qui change d'un cycle à l'autre.**

**Ce qui ne corrompt PAS la campagne (Claude) :** la mesure de foi est le
REJEU (`campagne.py`, hors ligne, le jour entier — la sortie existe toujours,
`libre_a` est juste, pas de re-rejeu). Le bug ne vit QUE dans le journal live
(« rodage », pas foi). Donc il ne fausse pas le verdict du jour 61 — il se
corrige avec EXEC (lundi), pas dans l'urgence d'avant-gel. Compatible avec le
gel : le chemin hors ligne ne change pas.

## 1. L'objet qui manque : l'INTENTION D'ENTRÉE

Entre la ligne PASSE (décision sur `t`) et l'ordre (acte sur `t+1`), rien.
Il faut un objet **immuable, idempotent, périssable** —
`LOGS/intentions/intentions_<jour>.jsonl`, un écrivain (le coureur) :

    {snapshot_id,            # = la ligne PASSE : clé d'idempotence
     sym, side, hypothese, ts_signal, contrat,
     entree: {type: "MKT", des: open(t+1), au_plus_tard: open(t+1)+delai_max_s},
     barriere: {sl_ticks, tp_ticks, expiration_barres},   # B-ATR, TICK[sym]
     taille: 1,
     etat: "EMISE"}          # EMISE -> EXECUTEE | EXPIREE | REFUSEE(motif) | ANNULEE

Le coureur émet ; il ne re-décide jamais. Une intention émise n'est ni
réécrite ni supprimée quand un cycle ultérieur re-ferme le signal — elle est
périmée par EXEC, ou reste EMISE avec une ligne `RETRO_BLOQUEE` à côté (pour
la lecture, jamais pour l'action). R8 appliqué à la décision : un journal qui
change d'avis n'est pas un journal.

## 2. Les neuf règles d'entrée — vérifiées par EXEC à `t+1`, sur l'état RÉEL

| # | règle | source de vérité | motif de refus |
|---|---|---|---|
| E1 | une position par instrument | `etat_<sym>.json` écrit par EXEC | `position_ouverte` |
| E2 | aucun ordre en vol | idem | `ordre_en_vol` |
| E3 | intention fraîche `now <= au_plus_tard` | horloge EXEC | `expiree` |
| E4 | pas de gap `\|open(t+1)-close(t)\| <= g*ATR-15m` | barre 1 min | `gap` |
| E5 | L0 live re-vérifiée à `t+1` (data, DTC, contrat, news, session) | portes L0 | `L0:<porte>` |
| E6 | stop journalier/prop firm | `pnl_jour` réel | `stop_journalier` |
| E7 | kill switch absent | fichier `STOP` | `kill` |
| E8 | contrat = `contrat_actif()` = fichier | calendrier + JSONL | `contrat` |
| E9 | idempotence `snapshot_id` jamais exécuté | journal EXEC | `doublon` |

Aucune condition de marché : L3/L4/L5 ont déjà parlé. EXEC ne trade pas mieux
que la chaîne ; il trade ce qu'elle a dit, si le monde n'a pas changé entre
`t` et `t+1`.

**[AJOUT Claude — E3 et E4 en OBSERVATION d'abord.]** `delai_max_s` (90 s) et
`g` (~0,3) sont des nombres INVENTÉS tant qu'ils ne sont pas mesurés. Règle
souveraine du projet : aucun seuil sans distribution. E3 et E4 JOURNALISENT
la grandeur (latence signal->ordre, gap SIGNÉ — pas `\|.\|`, le côté compte)
sans refuser, pendant assez de séances SIM pour bâtir la distribution, PUIS
deviennent des portes. Sinon on réintroduit « un seuil sans distribution » au
point d'entrée exact — le défaut qui a plombé le projet six fois.

## 3. Le contrat : coureur -> intention -> EXEC -> état -> coureur

    coureur (t clos) --PASSE--> intentions_<jour> --> EXEC (t+1 open)
       ^                                                    |
       |   etat_<sym>.json {position, ordres_en_vol,        |
       +-- pnl_jour, dernier_trade, contrat, ts_maj} <------+

- Le coureur LIT `etat_<sym>.json` pour POSITION_OUVERTE / ORDRE_EN_VOL /
  STOP_* / COOLDOWN en live. `_ouvrir()` (la simulation) ne sert QU'hors
  ligne — bascule par `live is not None`, et un test qui échoue si le coureur
  live appelle `triple_barriere`.
- EXEC écrit l'état atomiquement (`.tmp` + `os.replace`) ; `ts_maj` permet au
  coureur de lever `TROU_ETAT` si l'état a plus de N secondes — un état
  périmé est un trou, jamais un feu vert.
- `snapshot_id` traverse les trois journaux ; `pourquoi.py` dit alors pour
  chaque signal : retenu ? émis ? exécuté ? refusé pourquoi ? rempli à quel
  prix ? sorti comment ? — l'entonnoir complet.

## 4. La mesure qui répond à « ça fait trois fois »

- Latence par étape (signal -> intention -> ordre -> fill).
- Taux d'expiration (E3) et de refus par motif (E1-E9).
- Glissement réel contre `open(t+1)`.
- **Écart décision/exécution** : PASSE sans intention, intention sans `exec_`
  — doit être ZÉRO. S'il ne l'est pas, c'est l'incident qui a tué V1, vu le
  jour même au lieu de trois mois plus tard.

## 5. Tests avant le premier ordre

1. Coureur live n'appelle jamais `triple_barriere`.
2. Deux signaux avec position réelle ouverte -> second `REFUSEE:position_ouverte`.
3. Intention lue après `au_plus_tard` -> `EXPIREE`, pas d'ordre.
4. Gap > `g` -> `REFUSEE:gap` (une fois E4 en mode porte).
5. `STOP` présent -> `REFUSEE:kill` + `flatten_all`.
6. Même `snapshot_id` deux fois -> un ordre.
7. État périmé -> `TROU_ETAT`, blocage strict.
8. **[AJOUT Claude]** Réconciliation au boot : la vérité est
   `get_open_orders` DU BROKER, jamais le fichier d'état (qui peut être
   périmé après un crash). Position réelle sans intention -> alerte, aucun
   ordre tant qu'un humain n'a pas tranché. Le fichier se réconcilie SUR le
   broker, pas l'inverse (leçon V1).
9. Bout en bout sur faux DTC : signal -> intention -> fill -> TP -> plat ->
   signal suivant accepté.

## 6. Ordre de travail (lundi+)

1. `intentions.py` (émission depuis PASSE, idempotence) — 1/2 journée, 0 ordre.
2. `etat_exec.py` (écriture atomique + `TROU_ETAT`) + bascule live des portes
   POSITION_OUVERTE / ORDRE_EN_VOL / STOP_* / COOLDOWN sur l'état réel — 1/2
   journée, et les trois portes « inertes par construction » cessent de l'être.
3. EXEC (source DTC = **`BOT/dtc_connector.py` V2 validé, PAS V1** — cf
   PLAN_OPERATIONNEL) consommant les intentions avec E1-E9.
4. `pourquoi.py` lit les trois journaux par `snapshot_id`.

Rien ne touche à ce que la chaîne DÉCIDE (LES_QUATRE, L0, L5 gelés). Ça change
seulement QUAND et SUR QUEL ÉTAT une décision devient un acte.

## 7. Réserves de schéma — audit Fable 09/09 (à traiter au câblage / cycle 2)

- **B2 — B-NIV exige une intention en PRIX ABSOLUS, pas en ticks.** B-ATR est un
  multiple d'ATR → le bracket en ticks autour du fill est exact. Mais B-NIV pose
  le SL « derrière le niveau » à un PRIX figé : le niveau ne bouge pas, le fill
  si. Une intention en offsets-ticks ne peut pas l'exprimer. Quand B-NIV
  s'exécutera (cycle 2), le schéma d'intention doit porter `sl_prix`/`tp_prix`
  absolus pour les barrières de niveau, pas seulement `sl_ticks`.
- **C2 — `etat_exec.TTL_DEFAUT_S` = 60 s (deux battements), et EXEC ÉCRIT un
  battement toutes les 30 s même sans événement.** Sinon un état plat de 90 s
  est indiscernable d'EXEC mort. La valeur doit venir de `seuils`, pas d'une
  constante (aujourd'hui 120 provisoire, à corriger au pas 2b).
