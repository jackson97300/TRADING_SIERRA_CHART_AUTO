#!/bin/sh
# Publier V3 sur le miroir public, pour que Fable suive l'avancee.
#
#     sh V3/publier.sh
#
# Le miroir ne recoit QUE le dossier V3/ : du code, des conventions, des
# rapports agreges. Jamais de donnees, jamais d'identifiants, jamais de niveaux
# sous licence.
#
# TREIZE CONTROLES AVANT DE POUSSER, et le script s'arrete au premier qui echoue.
# Publier est IRREVERSIBLE : un secret pousse une seule fois reste dans
# l'historique meme supprime au commit suivant. C'est la raison d'etre du
# controle n.2 — il relit TOUTES les versions de tous les fichiers, pas l'etat
# courant.
set -e

DEPOT=https://github.com/jackson97300/mia-v3.git

echo "1/13  les portes repondent-elles ce qu'on attend ?"
python -X utf8 V3/layers/L0_interrupteur/test_portes.py

echo "2/13  et sur le vrai chemin de code, en faux live ?"
python -X utf8 V3/layers/L0_interrupteur/test_faux_live.py

echo "3/13  le calendrier bloque-t-il les bons jours ?"
python -X utf8 V3/tests/test_calendrier.py

echo "4/13  les fiches F23 decrivent-elles ce qui s'est passe ?"
python -X utf8 V3/tests/test_f23.py

echo "5/13 ce qui vient d'un proxy se refuse-t-il ?"
python -X utf8 V3/tests/test_proxys.py

echo "6/13 les ctx_* livrees se reproduisent-elles ?"
python -X utf8 V3/tests/test_ctx.py

echo "7/13 rvol_r et cvd_sess_r sont-elles dans l'agregation ?"
python -X utf8 V3/tests/test_recalc_agg.py

echo "8/13 les huit cas des C2 actifs sont-ils verts ?"
python -X utf8 V3/layers/L3_declencheurs/test_ombre_c2.py

echo "9/13 les cinq vetos L4 annulent-ils sans jamais compter ?"
python -X utf8 V3/layers/L4_orderflow/test_orderflow.py

echo "10/13 la SPEC L3 porte-t-elle les nombres du code tague ?"
python -X utf8 V3/tests/test_spec_l3.py

echo "11/13 l'intention d'entree : pure, idempotente, ZERO ordre ?"
python -X utf8 V3/tests/test_intentions.py

echo "12/13 rien de sensible, nulle part, dans aucune version ?"
python -X utf8 V3/tests/test_structure.py

echo "13/13 le travail est-il commite ?"
if ! git diff --quiet -- V3/ || ! git diff --cached --quiet -- V3/; then
    echo "     REFUS : des modifications de V3/ ne sont pas commitees."
    echo "     Le miroir doit refleter un etat scelle, pas un brouillon."
    exit 1
fi

git remote get-url v3pub >/dev/null 2>&1 || git remote add v3pub "$DEPOT"
git subtree push --prefix=V3 v3pub master

# Le tag de campagne doit etre identifiable SUR LE MIROIR (revue 08/09,
# A4) : un tag du depot principal ne survit pas au split — on tague la
# tete du miroir, une fois, jamais deplace ensuite. Le jour 61 doit
# pouvoir dire « le code qui a couru est <hash> » publiquement.
if git tag -l | grep -q "^campagne-ombre-1$"; then
    if ! git ls-remote --tags v3pub 2>/dev/null | grep -q "refs/tags/campagne-ombre-1$"; then
        # le split DU COMMIT TAGUE, jamais HEAD (review R2) : si HEAD a
        # avance, taguer son split publierait un AUTRE etat que le tag —
        # la divergence exacte que A4 rend impossible.
        split=$(git subtree split --prefix=V3 campagne-ombre-1)
        git push v3pub "$split:refs/tags/campagne-ombre-1"
        echo "tag campagne-ombre-1 pousse sur le miroir ($split)"
    fi
fi

echo
echo "publie : https://github.com/jackson97300/mia-v3"
