# AUDIT COMPLET — logique de trading du dashboard (08/09/2026)

*Demandé par Jackson après trois défauts trouvés en une séance. Trois agents
en parallèle : (A) reproduction empirique du pipeline, (B) audit backend
carte par carte, (C) vérité de l'écran (JS). Rapports complets dans les
sorties de tâches du 08/09 ; ceci est la synthèse actionnable.*

## Verdict d'architecture

**NEUF cerveaux calculent une direction côté serveur** (compute_bias,
_compute_bias_proxy, compute_regime, read_mtf_bias, _enrich_regime_with_mtf,
build_advisory, _stabilize_favor, build_conseil_global,
build_trade_suggestion) **plus CINQ côté navigateur** (réplique du conseil,
reconcileFavorWithMtf, override conseils, zones de confluence locales, feed
divergence 70/30). Les contradictions vues en séance ne sont pas des bugs
isolés — elles sont l'état d'équilibre du montage.

**Cible : un moteur + des vues.** Le seul à garder :
`CORE/regime_engine.compute_regime` (le seul audité 04/09, calibré par
instrument, avec garde-fou). Tout le reste devient de l'affichage du verdict
unique `{mode, direction, score, confiance, en_zone, fraîcheur}`.

## Réglé le 08/09 (déployé, vérifié en prod)

1. **Porte de lieu** (ES 6 t / NQ 40 t = P10 V3) + **véto MTF 4/4 opposé →
   CONFLIT** dans build_conseil_global — mesure pré-deploy : bloque 36,7 %
   des moments directionnels ES / 30,0 % NQ. Repro : 7 CONFLIT rejoués sur
   les 819 barres NQ du jour, le véto FONCTIONNE.
2. **Les émissions log étaient MORTES depuis le 08/06** (AttributeError
   avalée — INCIDENT_LOG 08/09) : fix get_logger déployé, première émission
   réelle constatée à 13:46:15Z, test d'émission ajouté
   (test_log_emission.py).
3. Le « VENTE PRUDENTE + MTF 4/4 » de 13:26 = **écran figé pendant la
   coupure du restart** (le JS garde le dernier état sur échec de fetch) —
   pas un bug du véto.

## Corrections classées (à arbitrer Jackson/Fable AVANT toute ligne)

1. **UN seul calcul de biais, mode-aware** : purger le double comptage
   delta/cvd (IDENTIQUES 600/600 barres mesurées — colonne condamnée par
   V3, 0,50 de poids pour un seuil à 0,25 : le delta cumulé du jour colorie
   la carte à lui seul) ; rétroporter le skip range_pos-en-TREND dans
   compute_bias ; un seul seuil d'étiquette (±0,30 vs ±0,25 aujourd'hui).
2. **Conditionner les votes fade du conseil** (range_pos ≥80 et DIV, sans
   condition de mode aujourd'hui) — les portes du 08/09 sont un filet aval,
   pas la correction.
3. **FAVORISER** : cliquet par BARRE (pas par poll — « 3 votes » = 15 s
   aujourd'hui), expiration du latch, stabiliser LE dict de la réponse pour
   ES (asymétrie : la carte ES montre un favor brut, la NQ un stabilisé).
4. **MTF** : la composante V (40 %) est LA MÊME VALEUR sur les 4 timeframes
   (prix vs VWAP jour) — le « 4/4 » est auto-corrélé ; normalisations non
   calibrées par instrument (V de NQ sature). Recalibrer, sinon dégrader en
   affichage sans boost ni véto.
5. **trade_suggestion** : porte de zone + session obligatoire + assert
   d'unité sur `atr` avant tout SL/TP affiché (colonne à unité non
   certifiée — le cas d'école du Check 1-2 de critical-tasks-review).
6. **JS pur afficheur** : supprimer reconcileFavorWithMtf (l'override MTF
   supprimé côté Python le 08/06 SURVIT côté navigateur et INVERSE le
   sens), rendre `cgBackend.checks` (les motifs HORS ZONE / VETO MTF sont
   invisibles aujourd'hui), migrer les zones de confluence côté Python,
   VIX 0 = TROU pas « calme », purge de la dédup du feed, supprimer
   dashboard.min.js d'avril de deploy.sh.
7. **tier_filter** : FREE voit précisément les deux sorties les plus
   défectueuses (action + bias) sans les checks ; order_flow_advanced fuit
   au tier STARTER.

## Règle de lecture pour Jackson d'ici les corrections

Niveaux / murs / SMT / MTF-grille : fiables (affichage de données saines).
Cartes directionnelles (BIAS, FAVORISER, checklist) : trois horloges
différentes, non fiables. Le SEUL verdict derrière des portes : le gros
CONSEIL GLOBAL. Et les zones qui comptent sont les tiennes.
