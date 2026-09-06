# STATUS — V3, l'etat des briques

*Le fichier a lire en premier. Une ligne par brique, trois etats possibles.*

| etat | ce que ca veut dire |
|---|---|
| **ecrite** | le code existe, rien n'est mesure |
| **mesuree** | on sait ce qu'elle rejette et ce que ses rejetes deviennent |
| **passee** | sa mesure est dans sa plage attendue — elle peut entrer dans la chaine |

**Regle du chantier** : une brique qui ne rejette rien, ou qui rejette tout, ne
passe pas a la suivante. C'est le garde-fou que V1 n'a jamais eu — il embarquait
27 modules dont personne ne savait ce que chacun filtrait.

---

## Briques

| # | brique | etat | rejet mesure | plage attendue | note |
|---|---|---|---|---|---|
| L0 | interrupteur — 9 portes + 5 declarees absentes | **mesuree** | 77,9 % ES / 77,4 % NQ (22,1 % retenus) | 15-30 % | portes evaluees INDEPENDAMMENT ; `POSITION_OUVERTE` exposee et ses refuses simules en fantomes |
| REG | regime (gamma HVL zone morte 1,0 ATR + largeur IB corrigee) | **mesuree** | — | 4 cases >= 5 jours | 99,7 % de couverture ES, 1,8 bascule/jour |
| L1 | biais 1h/4h (B1, B4, B5, B5b) | **ecrite** | — | 20-50 % | B1 seul pour l'instant |
| L3 | declencheurs 15 min | **ecrite** | — | N >= 40 par etage | 4 pre-enregistres + 16 en ombre |
| L4 | confirmation order flow 1 min | **absente** | — | 30-50 % | la seule couche a construire |
| L5 | risque — 3 vetos (gamma, rvol, frais/TP) | **mesuree** | cf `layers/L0_interrupteur/rapports/` | 10-25 % | PAS inerte : c'etait la mesure qui l'etait. Le veto SL mort remplace par la part des frais dans la distance au TP |
| L6 | surveillance donnees | **passee** | — | — | 7 controles quotidiens en place |

## Ou est quoi

Un dossier par couche, tout ce qui la concerne dedans : spec, seuils, code,
tests, mesure, rapports. Carte complete dans `LISEZ_MOI.md`.

## Calendrier immediat

**LUNDI 07/09/2026 — LABOR DAY.** 1er lundi de septembre, verifie. Le marche est
OUVERT mais ferme a 13:00 ET au lieu de 16:00 : seance raccourcie, aucun trade.

Deux consequences :
- la campagne d'ombre demarre le **mardi 08/09**, elle n'est pas touchee ;
- la surveillance L6 etait prevue lundi 21:01 UTC sur la premiere journee `w1`.
  **Une demi-seance est une mauvaise reference** — volumetrie, reset VWAP et
  fenetre seront tous atypiques. A decaler au mardi, ou a lire en sachant que
  les ecarts sont attendus.

## Prochain pas

Etape 1 : passer chaque couche existante sur les 57 jours, mesurer le taux de
rejet **et le devenir des rejetes**. Ce qui sort de sa plage est repare avant
d'aller plus loin.
