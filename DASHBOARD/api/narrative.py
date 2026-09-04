"""Generation de narration marche automatique.

Produit des paragraphes structures a partir des donnees JSONL.
"""
import logging

from CORE.constants import range_pos_pct as _range_pos_pct
from DASHBOARD.api.readers import (
    get_field,
    get_int_field,
)

logger = logging.getLogger(__name__)

OPEN_TYPE_NARR = {
    1: "en Open Drive haussier — les acheteurs ont pris le controle des l'ouverture",
    2: "en Open Drive baissier — les vendeurs ont domine des l'ouverture",
    3: "en Open Test Drive haussier — test du low suivi d'un rebond",
    4: "en Open Test Drive baissier — test du high suivi d'un rejet",
    5: "en Rejection Reversal haussier — faux mouvement baissier puis retournement",
    6: "en Rejection Reversal baissier — faux mouvement haussier puis retournement",
    7: "en Auction dans le range — pas de conviction directionnelle claire",
    8: "en Auction hors range haussier — gap up avec continuation",
    9: "en Auction hors range baissier — gap down avec continuation",
    10: "en Open Drive echoue (haussier) — tentative de drive mais echec = signal contrarian",
    11: "en Open Drive echoue (baissier) — tentative de drive mais echec = signal contrarian",
}


def generate_market_narrative(bar_es: dict, bar_nq: dict, cta_data: dict | None = None) -> list[str]:
    """Genere une narration du marche en paragraphes structures."""
    if not bar_es:
        return ["Pas de donnees disponibles pour generer la narration."]

    paragraphs = []

    # --- 1. Ouverture ---
    ot = get_int_field(bar_es, "open_type", 0)
    ot_text = OPEN_TYPE_NARR.get(ot, "sans pattern d'ouverture identifie")
    gap = get_field(bar_es, "open_gap_ticks", 0.0)
    gap_text = ""
    if abs(gap) > 5:
        gap_dir = "haussier" if gap > 0 else "baissier"
        gap_text = f" avec un gap {gap_dir} de {abs(gap):.0f} ticks"
    paragraphs.append(f"Le marche a ouvert {ot_text}{gap_text}.")

    # --- 2. Initial Balance ---
    ib_range = get_field(bar_es, "ib_range_ticks", 0.0)
    ib_broken_up = get_int_field(bar_es, "ib_broken_up", 0)
    ib_broken_down = get_int_field(bar_es, "ib_broken_down", 0)
    if ib_range > 0:
        ib_qual = "etroite" if ib_range < 40 else "normale" if ib_range < 80 else "large" if ib_range < 120 else "tres large"
        ib_text = f"L'Initial Balance (premiere heure) a forme un range de {ib_range:.0f} ticks — {ib_qual}."
        if ib_broken_up and ib_broken_down:
            ib_text += " L'IB a ete cassee dans les DEUX directions — marche indecis, rotation."
        elif ib_broken_up:
            ib_text += " L'IB a ete cassee vers le HAUT — les acheteurs ont pris l'initiative."
        elif ib_broken_down:
            ib_text += " L'IB a ete cassee vers le BAS — les vendeurs ont pris l'initiative."
        else:
            ib_text += " L'IB n'est pas encore cassee — le marche reste en range."
        paragraphs.append(ib_text)

    # --- 3. Structure du profil ---
    day_type = get_int_field(bar_es, "day_type", 0)
    day_labels = {0: "Non Trend", 1: "Normal", 2: "Normal Variation", 3: "Neutral", 4: "Trend"}
    day_label = day_labels.get(day_type, "Non Trend")
    # R3 (#99) : echelle unifiee [0,100] via la source canonique range_pos_va
    range_pos = _range_pos_pct(bar_es)

    pos_text = "au milieu du range"
    if range_pos >= 80:
        pos_text = "pres du plus haut de la session (TOP)"
    elif range_pos >= 60:
        pos_text = "dans la moitie haute du range"
    elif range_pos <= 20:
        pos_text = "pres du plus bas de la session (BOTTOM)"
    elif range_pos <= 40:
        pos_text = "dans la moitie basse du range"

    vpoc_dist = get_field(bar_es, "dist_cur_vpoc", 0.0)
    vpoc_rel = "en-dessous" if vpoc_dist > 0 else "au-dessus"
    paragraphs.append(
        f"Le jour est de type {day_label}. Le prix est {pos_text} "
        f"et se situe {vpoc_rel} du VPOC ({abs(vpoc_dist):.0f} ticks). "
    )

    # --- 4. VWAP & niveaux ---
    vwap_d = get_field(bar_es, "dist_vwap_d", 0.0)
    vwap_side = "en-dessous" if vwap_d > 0 else "au-dessus"
    vwap_w_side = get_int_field(bar_es, "bool_above_vwap_w", 0)
    vwap_m_side = get_int_field(bar_es, "bool_above_vwap_m", 0)
    triple = get_int_field(bar_es, "vwap_triple_align", 0)

    vwap_text = f"Le prix est {vwap_side} du VWAP Daily ({abs(vwap_d):.0f} ticks)"
    if triple > 0:
        vwap_text += ", au-dessus des VWAP Weekly et Monthly — alignement BULL complet."
    elif triple < 0:
        vwap_text += ", en-dessous des VWAP Weekly et Monthly — alignement BEAR complet."
    else:
        vwap_text += f", {'au-dessus' if vwap_w_side else 'en-dessous'} du Weekly, {'au-dessus' if vwap_m_side else 'en-dessous'} du Monthly."
    paragraphs.append(vwap_text)

    # --- 5. Order Flow ---
    delta_day = get_field(bar_es, "delta_day", 0.0)
    delta_dir = get_int_field(bar_es, "delta_day_dir", 0)
    cvd_dir = get_int_field(bar_es, "cvd_day_dir", 0)
    rvol = get_field(bar_es, "rvol", 0.0)

    flow_who = "les acheteurs" if delta_dir > 0 else "les vendeurs" if delta_dir < 0 else "personne"
    cvd_text = "accumulation" if cvd_dir > 0 else "distribution" if cvd_dir < 0 else "neutre"
    rvol_text = "extreme" if rvol > 3 else "eleve" if rvol > 2 else "au-dessus de la moyenne" if rvol > 1 else "calme"

    paragraphs.append(
        f"Cote flux, {flow_who} dominent le delta jour ({delta_day:+.0f}). "
        f"Le CVD est en phase de {cvd_text}. "
        f"Le volume relatif (RVOL) est {rvol_text} a {rvol:.1f}x."
    )

    # --- 6. Options / Gamma ---
    call_dist = get_field(bar_es, "dist_mq_call", 0.0)
    put_dist = get_field(bar_es, "dist_mq_put", 0.0)
    if call_dist and put_dist:
        corridor = abs(call_dist) + abs(put_dist)
        pct = abs(put_dist) / corridor * 100 if corridor > 0 else 50
        if pct > 75:
            gamma_text = f"Le prix est a {pct:.0f}% du corridor gamma — proche du Call Wall, risque de rejet baissier."
        elif pct < 25:
            gamma_text = f"Le prix est a {pct:.0f}% du corridor gamma — proche du Put Wall, support institutionnel."
        else:
            gamma_text = f"Le prix est a {pct:.0f}% du corridor gamma — zone neutre, pas de pression gamma directionnelle."
        paragraphs.append(gamma_text)

    # --- 7. VIX ---
    vix = get_field(bar_es, "vix_level", 0.0)
    if vix > 0:
        vix_regime = "extreme — prudence maximale" if vix > 30 else "eleve — stops elargis recommandes" if vix > 25 else "normal — conditions standard" if vix > 15 else "bas — faible volatilite attendue"
        paragraphs.append(f"Le VIX est a {vix:.1f} — regime {vix_regime}.")

    # --- 8. CTA / Institutionnel ---
    if cta_data and "today" in cta_data and cta_data["today"]:
        cta = cta_data["today"].get("CTA", {})
        es_cta = cta.get("ES", {})
        es_pos = es_cta.get("position_today", 0)
        if abs(es_pos) > 0.3:
            cta_dir = "SHORT" if es_pos < 0 else "LONG"
            paragraphs.append(
                f"Les CTA institutionnels sont {cta_dir} sur ES ({es_pos:+.2f}). "
                f"{'Attention au squeeze si le marche monte contre eux.' if es_pos < -1 else 'Attention au sell-off si le marche casse un support.' if es_pos > 1 else ''}"
            )

    # --- 9. Conclusion ---
    bias = "BULL" if delta_dir > 0 and (vwap_d or 0) < 0 else "BEAR" if delta_dir < 0 and (vwap_d or 0) > 0 else "NEUTRE"
    if bias == "BULL":
        conclusion = "Le contexte est globalement haussier. Les flux et la structure supportent les acheteurs."
    elif bias == "BEAR":
        conclusion = "Le contexte est globalement baissier. Les flux et la structure favorisent les vendeurs."
    else:
        conclusion = "Le contexte est mixte. Prudence — attendre une confirmation directionnelle avant de prendre position."
    paragraphs.append(conclusion)

    return paragraphs
