#!/bin/sh
# Publier V3 sur le miroir public, pour que Fable suive l'avancee.
#
#     sh V3/publier.sh
#
# Le miroir ne recoit QUE le dossier V3/ : du code, des conventions, des
# rapports agreges. Jamais de donnees, jamais d'identifiants, jamais de niveaux
# sous licence.
#
# SEPT CONTROLES AVANT DE POUSSER, et le script s'arrete au premier qui echoue.
# Publier est IRREVERSIBLE : un secret pousse une seule fois reste dans
# l'historique meme supprime au commit suivant. C'est la raison d'etre du
# controle n.2 — il relit TOUTES les versions de tous les fichiers, pas l'etat
# courant.
set -e

DEPOT=https://github.com/jackson97300/mia-v3.git

echo "1/7  les portes repondent-elles ce qu'on attend ?"
python -X utf8 V3/layers/L0_interrupteur/test_portes.py

echo "2/7  et sur le vrai chemin de code, en faux live ?"
python -X utf8 V3/layers/L0_interrupteur/test_faux_live.py

echo "3/7  le calendrier bloque-t-il les bons jours ?"
python -X utf8 V3/tests/test_calendrier.py

echo "4/7  les fiches F23 decrivent-elles ce qui s'est passe ?"
python -X utf8 V3/tests/test_f23.py

echo "5/7  ce qui vient d'un proxy se refuse-t-il ?"
python -X utf8 V3/tests/test_proxys.py

echo "6/7  rien de sensible, nulle part, dans aucune version ?"
python -X utf8 V3/tests/test_structure.py

echo "7/7  le travail est-il commite ?"
if ! git diff --quiet -- V3/ || ! git diff --cached --quiet -- V3/; then
    echo "     REFUS : des modifications de V3/ ne sont pas commitees."
    echo "     Le miroir doit refleter un etat scelle, pas un brouillon."
    exit 1
fi

git remote get-url v3pub >/dev/null 2>&1 || git remote add v3pub "$DEPOT"
git subtree push --prefix=V3 v3pub master

echo
echo "publie : https://github.com/jackson97300/mia-v3"
