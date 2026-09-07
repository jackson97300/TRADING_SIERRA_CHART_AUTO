# Distribution de finish_delta_pct sur les barres de LIEU H3 (15 min)

*Mesure du 07/09 (audit Fable, demande n.1) : que filtre le seuil
0,4/0,6 herite du cycle 1, jamais pose sur une distribution ?*

## ES — 58 barres de lieu sur 20 jours

| quantile | valeur |
|---|---|
| p05 | 0.0459 |
| p10 | 0.0625 |
| p25 | 0.1631 |
| p50 | 0.3693 |
| p75 | 0.7737 |
| p90 | 0.9150 |
| p95 | 0.9630 |

- valeurs distinctes : 50 — GRADUEE
- exactement 0,0 : 3.4 % ; exactement 1,0 : 5.2 %
- **ce que `< 0,4` filtre (short H3)** : garde 55.2 % des barres de lieu
- **ce que `> 0,6` filtre (long H3)** : garde 34.5 % des barres de lieu

## NQ — 61 barres de lieu sur 20 jours

| quantile | valeur |
|---|---|
| p05 | 0.0488 |
| p10 | 0.0776 |
| p25 | 0.2273 |
| p50 | 0.5490 |
| p75 | 0.8281 |
| p90 | 0.9000 |
| p95 | 0.9245 |

- valeurs distinctes : 61 — GRADUEE
- exactement 0,0 : 0.0 % ; exactement 1,0 : 0.0 %
- **ce que `< 0,4` filtre (short H3)** : garde 41.0 % des barres de lieu
- **ce que `> 0,6` filtre (long H3)** : garde 45.9 % des barres de lieu
## Conclusion — ce que la mesure change a l'audit

Sur les barres ou H3 DECIDE (lieu P10, 15 min), la colonne est GRADUEE sur
les DEUX instruments — la binarite constatee la nuit vivait sur le 1 min
(l'agregation 15 min prend la DERNIERE minute, cf INCIDENT_LOG 07/09, et sur
le sous-ensemble des rejets d'extreme la derniere minute n'est presque jamais
saturee). Le vrai constat au site de decision : le seuil 0,4/0,6 garde
55 % (ES) / 41 % (NQ) des barres de lieu — un filtre MOU, pas un rasoir.
La critique STRUCTURELLE tient : formule C++ inconnue, seuil herite jamais
pose sur cette distribution. finish_r recalcule reste la 1re ligne du cycle 2.
