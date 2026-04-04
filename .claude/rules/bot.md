---
paths:
  - "BOT/**"
---

# Regles BOT

- Toujours tester avec `python -X utf8 BOT/test_bot.py` apres modification
- DTC : OrderStatus 7=Filled, 2=Open. JAMAIS traiter 2 comme Filled
- Cancel ordre : TOUJOURS inclure ServerOrderID + ClientOrderID + TradeAccount
- OCO : TOUJOURS manuel (3 ordres Type 208). Type 206 et OCOGroup1 ne marchent PAS
- Deployer sur VPS avec SCP apres chaque modification validee
- Ne JAMAIS envoyer d'ordre sans confirmation de position = 0 d'abord
- Connexion DTC persistante — ne pas fermer tant que des brackets sont actifs
