# Les couches

**Ce dossier ne contient pas tout.** Si vous êtes arrivé directement ici, il
manque la moitié du système — remontez à la [racine du dépôt](../).

Trois fichiers vivent à la racine et sont indispensables pour juger une couche :

| à la racine | pourquoi il compte |
|---|---|
| [`registre.py`](../registre.py) | le registre des portes, et la règle « toutes évaluées indépendamment » |
| [`lecture.py`](../lecture.py) | **le seul endroit qui calcule** — les portes ne font que comparer |
| [`chaine.py`](../chaine.py) | applique, journalise, et simule les refusés en trades fantômes |
| [`config/sessions.yaml`](../config/sessions.yaml) | fériés CME, demi-séances, journées en panne |
| [`STATUS.md`](../STATUS.md) · [`DECISIONS.md`](../DECISIONS.md) | l'état des briques, et les arbitrages avec leur mesure |

Une porte qu'on lit sans `lecture.py` paraît incomplète : elle ne calcule rien,
c'est voulu. Elle compare une valeur déjà préparée, ce qui la rend testable avec
un dictionnaire de trois clés.

## Une couche par dossier

| dossier | question |
|---|---|
| [`L0_interrupteur/`](L0_interrupteur/) | a-t-on le **droit** de trader, là, maintenant ? |
| [`REG_regime/`](REG_regime/) | quel marché : gamma HVL, largeur IB |
| [`L1_biais/`](L1_biais/) | dans quel sens penche 1 h / 4 h ? |
| [`L3_declencheurs/`](L3_declencheurs/) | qu'est-ce qui déclenche, en 15 min ? |
| [`L4_orderflow/`](L4_orderflow/) | le flux confirme-t-il, en 1 min ? |
| [`L5_risque/`](L5_risque/) | combien, et où est le stop ? |
| [`L6_surveillance/`](L6_surveillance/) | les données du jour sont-elles saines ? |

Tout ce qui concerne une couche est dans son dossier : sa spec, ses seuils, son
code, ses tests, sa mesure, ses rapports. Rien de cette couche ne vit ailleurs
— à l'exception des trois modules communs listés plus haut, qui n'appartiennent
à aucune couche parce qu'ils les servent toutes.
