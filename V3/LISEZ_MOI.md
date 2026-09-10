# V3 — quoi est ou

*Le depot est organise PAR COUCHE, pas par type de fichier. On ouvre le dossier
d'une couche et tout ce qui la concerne y est : sa spec, ses seuils, son code,
ses tests, sa mesure, ses rapports. C'est ce que V1 n'avait pas — 27 modules
eparpilles dont personne ne savait ce que chacun filtrait.*

```
V3/
  STATUS.md            l'etat des briques — a lire en premier
  DECISIONS.md         les arbitrages, avec leur date et leur mesure
  LISEZ_MOI.md         ce fichier

  registre.py          le registre des portes — une porte n'existe que declaree ici
  lecture.py           prepare une barre pour les portes : le SEUL endroit qui calcule
  lecture_colonnes.py  les NOMS de colonnes (REQUISES, SOURCES_DECLAREES) et les convertisseurs
  chaine.py            evalue tout, applique, et SIMULE ce qu'elle refuse (fantomes)

  config/              ce qui est partage entre couches
    sessions.yaml        feries CME, demi-seances, journees en panne
    campagne.yaml        la campagne d'ombre
    comptes.example.yaml modele — les vrais comptes sont hors depot

  layers/
    L0_interrupteur/   a-t-on le DROIT de trader, la, maintenant ?
      SPEC.md            la source de verite ; le code en decoule
      BRIEF.md           la demande d'origine et les 7 questions
      seuils.yaml        TOUS les nombres et TOUTES les classes
      portes.py          9 portes L0, trois lignes chacune
      test_portes.py     une barre qui passe, une qui bloque, par porte
      mesure_57j.py      ce que chaque porte ferme sur 57 jours
      rapports/          les CSV de mesure, versionnes
    REG_regime/        quel marche : gamma HVL + largeur IB
    L1_biais/          le biais 1h / 4h
    L3_declencheurs/   les setups 15 min
    L4_orderflow/      la confirmation 1 min — LA SEULE COUCHE A CONSTRUIRE
    L5_risque/         combien, et ou est le stop
      vetos.py           3 vetos, la seule couche qui lit le SENS du trade
    L6_surveillance/   les controles quotidiens sur les donnees

  scenarios/           le module SCENARIOS — le narrateur de seance (spec : SCENARIOS_SPEC.md ; ordre : MISSION.md)
    lot.py             le lot des 57 jours avec le metre `atr_ref`, et `seuils()` — la seule source des nombres
    seuils.yaml        chaque nombre FIXE par Fable sur sa distribution, ecrite a cote ; null = pas fixe
    zones.py           les zones : bande asymetrique (dedans P10 / dehors p80), memoire F23 causale, roles
    grammaire.py       les huit canoniques v0 : sequences d'etats dates, validations / invalidations / bascules
    scenarios.py       la journee deroulee barre a barre ; rejeu et direct par la MEME fonction ; le journal
    sorties.py         B-SCEN : ou le scenario finit (devant la cible), ou il meurt (derriere l'invalidation)
    erreurs.py         l'auto-evaluation du soir : sept erreurs nommees, le carnet ; note, ne regle pas
    SPEC_VITRINE.md    les cinq phrases que la vitrine ne franchit jamais (frontiere, mots interdits)
    boucle.py          L'ECRIVAIN : un processus, recalcule la journee a chaque barre -> direct_<jour>.jsonl
    vitrine.py/.html   la page sans etat (localhost:8765) : lit le journal, n'ecrit que NOTER et MUET
    fenetre.py         la meme page, epinglee au premier plan (pywebview)
    alertes.py         sonne sur cinq EVENEMENTS, jamais sur un etat ; muet ; silence 9h30-9h35
    noter.py           le bouton NOTER -> journal manuel, HORS_SCENARIO, scenarios_visibles
    direct.py          les prerequis de la journee en cours, lecture seule -> prerequis_<jour>.jsonl
  execution/garde_scenarios.py  relance l'ecrivain si son coeur s'arrete (toutes les 5 min, backoff)
    mesure_*.py        prerequis 1-3 et les trois mesures de la grammaire (couverture, tenue, tirage au sort)
    rapports/          les distributions, ecrites AVANT tout usage
  publier.sh           publie le miroir public (3 controles, puis subtree push)
  tests/test_structure.py   le garde-fou du miroir public, en pre-commit
```

## Les trois regles qui gouvernent ce dossier

1. **Un seuil ne s'ecrit jamais dans le code.** Il vit dans le `seuils.yaml` de
   sa couche, avec sa **distribution mesuree ecrite a cote**. Six confusions
   d'unites en une semaine ; deux hypotheses rendues non testables par des
   seuils hors distribution.
2. **Une porte n'existe que si elle est declaree.** `test_portes.py` echoue si
   une porte du code n'a pas de ligne YAML, ET si une ligne YAML n'a pas de
   porte. Le controle va dans les deux sens.
3. **Bloquer et mesurer ce que bloquer coute sont le meme geste.** Une porte
   qui ne rejette rien est *inerte*, une porte qui rejette tout est
   *etrangleuse* — ni l'une ni l'autre ne passe a la couche suivante.
