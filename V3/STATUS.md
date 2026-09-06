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
| L0 | interrupteur (session, news, max trades, stop journalier) | **mesuree** | 50 % (H7, ES 03/09) | 15-30 % | `L0_MAX_TRADES_JOUR` ferme a lui seul la moitie des signaux |
| REG | regime (gamma HVL zone morte 1,0 ATR + largeur IB corrigee) | **mesuree** | — | 4 cases >= 5 jours | 99,7 % de couverture ES, 1,8 bascule/jour |
| L1 | biais 1h/4h (B1, B4, B5, B5b) | **ecrite** | — | 20-50 % | B1 seul pour l'instant |
| L3 | declencheurs 15 min | **ecrite** | — | N >= 40 par etage | 4 pre-enregistres + 16 en ombre |
| L4 | confirmation order flow 1 min | **absente** | — | 30-50 % | la seule couche a construire |
| L5 | risque (veto mur, veto SL, taille) | **mesuree** | **0 %** | 10-25 % | **inerte** : aucun veto sur 1 300 signaux |
| L6 | surveillance donnees | **passee** | — | — | 7 controles quotidiens en place |

## Prochain pas

Etape 1 : passer chaque couche existante sur les 57 jours, mesurer le taux de
rejet **et le devenir des rejetes**. Ce qui sort de sa plage est repare avant
d'aller plus loin.
