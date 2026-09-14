# À faire — état au soir du 14/09/2026

Journée entière sur L1 et les conventions. **Trois commits passés** (`ac36903`
le correctif du signe, `55fac08` le registre, `b224dec` les specs). Rien n'est
poussé. Ce fichier existe pour qu'aucune des trouvailles ne se reperde.

**Règle qui s'applique à tout ce qui suit** (Jackson, 14/09) : une
recommandation de review **se vérifie et se teste avant d'être appliquée**.
Aujourd'hui la review a eu raison sur le signe (vérifié par balayage de 25
colonnes, sabotage, et confrontation au prix brut) et **tort** sur les trous du
matin (mesuré : zéro sur 1394 barres). Rien ne distinguait les deux avant la
mesure.

---

## 1. BLOQUANT — avant toute mise en ligne

- [ ] **Le chemin d'ordre. R1, R2, R3, non commités.**
      Dont la traduction **`BuySell = ±1` côté bot contre `1/2` en DTC**.
      C'est la **même famille de bug** que celui d'aujourd'hui — une convention
      non vérifiée — sauf qu'ici un signe inversé **envoie le mauvais côté au
      broker**. Plus : garde de position nue, `sys.path` du connecteur.
      *Protocole* : attendu écrit avant, vérification contre ce que Sierra a
      **réellement reçu**, sabotage, puis `--un-tour` réel sur le compte SIM.
      **Ne rien committer avant le tour réel.**

- [ ] **Vérifier que `big_ask_cluster_*` / `big_bid_cluster_*` sont vivantes.**
      16 features mortes **26 jours** avant d'être réparées le 13/04. C1 de la
      checklist repose dessus. À passer par le registre.

---

## 2. LA CHECKLIST DE CONFIRMATION — le chantier principal

Spec : `V3/layers/L1_biais/CHECKLIST_CONFIRMATION.md`.
Objectif chiffré : **faire baisser les 85 % (ES) / 90 % (NQ) de stops touchés**
sur une entrée au niveau sans confirmation (mesuré le 14/09, 306 et 244 entrées).

- [ ] Coder les dix items, chacun rendant **`True` / `False` / `None`**.
      `None` n'est pas `False`.
- [ ] Sortie **vectorielle**, plus les trois comptes. **Aucun score, aucun
      seuil, aucun blocage.**
- [ ] Journaliser le vecteur sur **CHAQUE** décision, y compris celles qu'on ne
      prend pas — sinon `PERSONNE` ne produit aucune mesure et le contrefactuel
      est perdu.
- [ ] Chaque colonne utilisée doit d'abord **entrer au registre** avec sa
      convention mesurée.
- [ ] **C11 pullback** : non retenu pour l'instant. Exige une définition de
      jambe, donc F23, et une jambe n'est connue qu'une fois finie — look-ahead.
      À construire avec la lecture par jambe, pas avant.

---

## 3. L1 — ce qui reste

- [ ] **H6 et H8 ne tirent JAMAIS** sur ce chemin. `ES : H7 n=542, H3 n=25,
      H6 = 0, H8 = 0` — H7 porte **96 %** de tout. Colonne manquante ou défaut
      des hypothèses ? À trancher avant d'en tirer quoi que ce soit.

- [ ] **Câbler les cinq clés mortes**, par ordre de risque croissant :
      1. `open_vs_va` et `barres_inside_prev_va` — la recette existe déjà dans
         le dépôt (`mesure_57j` l.109-111), et `inside_prev_va` est vérifiée à
         100 % contre les niveaux reconstruits
      2. `smt_div` — `im_smt_divergence`, 390/390 non nulles, mais absente du
         frame 15 min : il faut la porter
      3. `d_vwap_w_autre` — croise deux instruments, alignement par `ts` et
         jamais par indice ; en live exiger la barre close
      4. `issue_vwap_w` — **le plus risqué** : « le test a tenu » n'est un fait
         qu'après la fenêtre de réaction. Look-ahead si mal posé.

- [ ] **Test de causalité générique** : `lire(df[:i+1], i)` doit rendre
      exactement `lire(df, i)`. Attention, il échouerait aujourd'hui sur
      `_fenetre_melangee`, qui lit `window_version` sur la journée entière.

- [ ] **Relancer `mesure_57j`** avec le signe corrigé — mais **attendu écrit
      AVANT**. Inverser B1 échange `avec` et `contre`, donc chaque écart publié
      change de signe : un correctif de bug peut transformer un échec en
      réussite, et c'est la configuration la plus dangereuse du dépôt.

- [ ] **Tester le biais de DOMINATION** (orderflow : absorption, pression, gros
      ordres). Les 48 tests d'alignement n'ont porté que sur des indicateurs de
      **position**. La porte n'est pas fermée, elle n'a pas été ouverte.

- [ ] **Le biais par jambe sur F23** — une lecture datée, pas un biais par
      barre. C'est la seule forme avec un soutien externe (JFE 2018, R² OOS
      1,7-2,5 %, 11 instruments). Le nombre de jambes par jour est un réglage
      d'hystérésis (`z_reset_atr`).

- [ ] **`prev_vah` / `prev_val`** désignent un autre niveau que
      `dist_prev_vah` / `dist_prev_val` — écart jusqu'à **63 points**. V3 reste
      cohérent (il n'utilise que les distances), mais l'anomalie est réelle et
      non résolue.

- [ ] **Pré-enregistrer la relance du test d'alignement au jour 61** —
      52 → 113 sessions. À écrire **avant** de voir quoi que ce soit.

---

## 4. LA REVUE DES COUCHES

- [x] L0 — interrupteur (fait le 13/09)
- [x] L1 — biais (fait le 14/09)
- [ ] **L4 — orderflow**
- [ ] **L5 — risque**
- [ ] **L6 — surveillance**
- [ ] **REG — régime**

On ne branche rien de neuf avant d'avoir fini.

---

## 5. DÉFAUTS TROUVÉS EN PRODUCTION, HORS V3

Trouvés aujourd'hui pendant l'audit. **Ils touchent les bots qui tournent.**

- [ ] **`bias_calculator_v6` porte toujours le bug d'échelle `range_pos`**,
      trois mois après sa correction dans la v1. Mesuré : **99,4 % de barres
      bull, 0,0 % bear** sur ES. Le gate qu'il alimente bloquerait un SHORT sur
      28,8 % des barres contre un LONG sur 0,45 % — **asymétrie ×64**.

- [ ] **Le MTF lit la barre 60 min non clôturée.** Exclure le bucket en cours
      change le verdict sur **46,5 % (ES) / 50,1 % (NQ)** des instants. Et
      `read_mtf_bias(symbol)` n'accepte aucun instant `t` : en rejeu, c'est du
      look-ahead franc.

- [ ] **40 % du score MTF est le même nombre copié quatre fois** —
      `vwap_score` identique bit-à-bit sur 1m/5m/15m/1h, **1019 instants sur
      1019**. Un « 4/4 » vaut environ **un** témoignage.

- [ ] **L'hypothèse écrite dans `builders.py:1222` est fausse ×5 à ×50** :
      « MTF perfect est rare ~1-5 % » ; mesuré **24,5 % ES / 53,7 % NQ**.

- [ ] **Le front annule un correctif du back.** `stabilizers.py:107-110` retire
      l'override MTF ; `dashboard.js:1838-1852` le refait en JavaScript et
      **gagne à l'écran**. Trois commentaires justifient le fix en citant une
      mémoire `feedback_mtf_no_override.md` **qui n'existe pas**.

- [ ] **Deux dicts `regime` coexistent pour ES, l'écran lit le mauvais.** Le
      FAVORISER d'ES n'est pas stabilisé et sa fraîcheur est morte. NQ
      fonctionne. Asymétrie invisible.

- [ ] **BIAS et QUI A LA MAIN se contredisent 30,5 % du temps** (3 481 barres
      sur 11 416), dont **637 où l'écran affiche « Aucune direction » au-dessus
      de « ACHETEURS — FORTE »**.

- [ ] **`AUDIT_DEAD_FEATURES_RESOLUTION_20260615.md:100`** affirme que
      `delta_cvd_divergence` détecte une vraie divergence. Mesuré : **0,0 %**
      de déclenchement. L'audit a tort, le code le dit lui-même (« DORMANT »).

---

## 6. DETTES ANCIENNES, toujours ouvertes

- [ ] `x_natif` dans `LOGS/marges/`
- [ ] `sans_devenir` mono-niveau ; la règle par setup reste à arbitrer
- [ ] Quatre lots de mesure sans borne supérieure
- [ ] `CORE/bot_terminal.py --journal` contourne la garde
- [ ] `lot.TICK` non gardé
- [ ] `declencheurs.py` : `TICK = 0.25` en dur avec un paramètre `sym` inutilisé
      — violation de `.claude/rules/tick-size-policy.md`
- [ ] **L'ES mérite-t-il sa place ?** 2 669 $ de frais sur 61 jours pour
      2 MES, contre un drawdown de 2 000 $. Décision arithmétique, pas
      stratégique.

---

## 7. PUBLICATION ET VPS

- [ ] **Rien n'est poussé.** Quatre commits du 14/09 plus ceux du 13 sont
      locaux.
- [ ] **La bascule VPS** (`V3/BASCULE_VPS.md`) — toujours pas faite. Le VPS
      tourne pandas 3.0.2, hors de la liste testée, avec du code d'avant le gel.
      Règle posée : « la bascule et rien d'autre ce jour-là ».
- [ ] **La fuite publique du 09/09** — réécriture d'historique, planifiée,
      non faite.
- [ ] **Commit des fichiers prop firm** — `calendrier.py`, `exec_sim.py`,
      `test_exec_sim.py`, `comptes.py`. Hors périmètre L1, leur propre commit.

---

## CE QU'IL NE FAUT PAS REFAIRE

Trois escaliers testés le 14/09 — les crans de B1p, les grades de BotBN,
l'alignement multi-unités — sont **tous les trois non monotones**. **Ne jamais
présumer qu'un cran « plus fort » est meilleur : le mesurer.**

Et quatre erreurs de méthode commises dans l'audit lui-même, toutes de la même
forme — comparer à la mauvaise référence : CVD cumulé à travers les journées,
ATR d'une minute contre un true range de quinze, moyenne agrégée au lieu d'un
examen jour par jour, verdict rendu sur un seul jour tombé un férié.
