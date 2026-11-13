# -*- coding: utf-8 -*-
"""
figures.py — Génération automatique des figures DREAL pour un point de vue.

Produit deux PNG dans le dossier de sortie :
  1. <nom_projet>_polaire_Sc<N>.png  — graphique polaire angulaire (wedges réels)
  2. <nom_projet>_synthese.png        — tableau 4 scénarios × 6 indices

Appelé automatiquement depuis processAlgorithm après les calculs.
Backend matplotlib Agg (headless, compatible QGIS).

Inputs attendus :
  resultats       dict {sc_id: {IOH, IER, ID1, ID2_10km, alerte_*, ...}}
  secteurs        dict {sc_id: [{"tmin", "tmax", "couronne", "statut",
                                 "parc", "is_projet"}, ...]}
  output_dir      str  dossier de sortie (même que le CSV)
  nom_projet      str  apparaît dans les titres et noms de fichiers
  scenario_polaire int scénario représenté sur le polaire (défaut : 2)
"""

import os
import math

# ── Matplotlib headless ──────────────────────────────────────────────────────
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import matplotlib.gridspec as gridspec
    import numpy as np
    MPL_OK = True
except ImportError:
    MPL_OK = False


# ── Palette ──────────────────────────────────────────────────────────────────
GREY_BG  = "#F7F8FA"
C_IER    = "#2ECC71"
C_WARN   = "#E74C3C"
C_OK     = "#27AE60"
COULEURS_STATUT = {
    "En service":     "#2C7BB6",
    "Autorisé":       "#74ADD1",
    "En instruction": "#ABD9E9",
    "Projet":         "#E8533F",
}

# ── Seuils DREAL ─────────────────────────────────────────────────────────────
SEUIL_IOH = 120.0
SEUIL_IER = 160.0
SEUIL_ID1 = 0.1
SEUIL_ID2 = 0.25


# ════════════════════════════════════════════════════════════════════════════
#  Utilitaire : conversion azimut géo → radian matplotlib polar
# ════════════════════════════════════════════════════════════════════════════

def _geo2mpl(az_deg):
    """
    Azimut géographique (horaire, Nord=0) → radian matplotlib polar.
    Valide avec set_theta_zero_location("N") + set_theta_direction(-1) :
    les axes sont déjà en convention géographique, conversion = radians directs.
    """
    return math.radians(az_deg)


# ════════════════════════════════════════════════════════════════════════════
#  Dessin d'un secteur de couronne annulaire
# ════════════════════════════════════════════════════════════════════════════

def _ier_depuis_iv_fus(iv_tous_fus):
    """IER exact depuis la liste d intervalles fusionnes (meme logique que calculer_ier)."""
    if not iv_tous_fus:
        return 0.0, 0.0, 0.0
    fus = sorted(iv_tous_fus, key=lambda x: x[0])
    best_s, best_l = 0.0, 0.0
    n = len(fus)
    for i in range(n):
        gap_s = fus[i][1]
        gap_e = fus[(i + 1) % n][0]
        if i == n - 1:
            gap_e += 360.0
        gap_l = gap_e - gap_s
        if gap_l > best_l:
            best_l  = gap_l
            best_s  = gap_s % 360.0
    return best_s, best_s + best_l, best_l



def _convergence_lambert93(x_l93, y_l93):
    """
    Convergence des méridiens en Lambert-93 (EPSG:2154).

    Retourne l'angle en degrés entre le Nord Lambert (utilisé pour le
    calcul des azimuts SIG) et le Nord géographique réel.

    Cette valeur est utilisée pour orienter le graphique polaire afin
    que sa superposition directe sur un fond cartographique soit exacte,
    sans rotation manuelle.

    Valeurs typiques sur la France métropolitaine :
      Bretagne (ouest)  : ~ -3°
      Île-de-France     : ~  0°
      Alsace (est)      : ~ +3°

    Signe :  positif = Nord Lambert est à l'est du Nord géographique
             négatif = Nord Lambert est à l'ouest du Nord géographique

    :param x_l93: coordonnée X Lambert-93 (m)
    :param y_l93: coordonnée Y Lambert-93 (m)
    :returns: convergence en degrés (float)
    """
    import math

    # Constante de projection Lambert-93 (valeur exacte EPSG:2154)
    N_CONE          = 0.7256077650
    LON_CENTRALE    = 3.0           # méridien central Lambert-93 (°Est)
    DEG_PAR_METRE   = 1.0 / 76_627.0  # approximation locale : 1° lon ≈ 76 627 m à 46,5°N

    try:
        # Priorité : pyproj disponible dans l'environnement QGIS/OSGeo4W
        from pyproj import Proj
        p = Proj("EPSG:2154")
        lon, lat = p(x_l93, y_l93, inverse=True)
    except (ImportError, Exception):
        # Fallback : approximation analytique (précision ~0,1° sur la France)
        lon = LON_CENTRALE + (x_l93 - 700_000.0) * DEG_PAR_METRE

    return N_CONE * (lon - LON_CENTRALE)


def _dessiner_secteur(ax, tmin, tmax, r_in, r_out, color, alpha=0.65):
    amp = min(tmax - tmin, 360.0)
    if amp <= 0:
        return
    n = max(64, int(amp * 1.5))
    angles = np.linspace(tmin, tmin + amp, n)
    th_ext = [_geo2mpl(a) for a in angles]
    th_int = [_geo2mpl(a) for a in reversed(angles)]
    ax.fill(
        th_ext + th_int,
        [r_out] * n + [r_in] * n,
        color=color, alpha=alpha,
        linewidth=0.2, edgecolor="white", zorder=2,
    )


# ════════════════════════════════════════════════════════════════════════════
#  Calcul IER visuel depuis la liste des intervalles fusionnés
# ════════════════════════════════════════════════════════════════════════════

def _ier_depuis_secteurs(secteurs_sc):
    """Recalcule le plus grand arc libre depuis les secteurs du scénario."""
    tous = []
    for s in secteurs_sc:
        tous.append((float(s["tmin"]), float(s["tmax"])))

    if not tous:
        return 0.0, 0.0, 0.0

    # Fusion simple
    tous_s = sorted(tous, key=lambda x: x[0])
    fus = [tous_s[0]]
    for t1, t2 in tous_s[1:]:
        if t1 <= fus[-1][1]:
            fus[-1] = (fus[-1][0], max(fus[-1][1], t2))
        else:
            fus.append((t1, t2))

    best_s, best_l = 0.0, 0.0
    n = len(fus)
    for i in range(n):
        gap_s = fus[i][1]
        gap_e = fus[(i + 1) % n][0]
        if i == n - 1:
            gap_e += 360.0
        gap_l = gap_e - gap_s
        if gap_l > best_l:
            best_l  = gap_l
            best_s  = gap_s % 360.0
    return best_s, best_s + best_l, best_l


# ════════════════════════════════════════════════════════════════════════════
#  FIGURE 1 — Graphique polaire (un scénario)
# ════════════════════════════════════════════════════════════════════════════

def _figure_polaire(resultats, secteurs, scenario_id, nom_projet, output_dir,
                    convergence_deg=0.0):
    sc_data  = resultats.get(scenario_id, {})
    sects_sc = secteurs.get(scenario_id, [])

    sc_noms = {
        1: "Sc.1 — En service + Autorisé",
        2: "Sc.2 — + Projet",
        3: "Sc.3 — + En instruction",
        4: "Sc.4 — + En instruction + Projet",
    }

    fig = plt.figure(figsize=(14, 8), facecolor=GREY_BG)
    fig.patch.set_facecolor(GREY_BG)
    gs  = gridspec.GridSpec(1, 2, width_ratios=[1.1, 0.9], wspace=0.05)

    # ── Panneau polaire ──────────────────────────────────────────────────────
    ax = fig.add_subplot(gs[0], projection="polar")
    ax.set_facecolor(GREY_BG)
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)

    # Correction convergence des méridiens Lambert-93
    # Aligne le Nord du graphique sur le Nord géographique pour
    # superposition directe sur fond cartographique sans rotation manuelle.
    if convergence_deg != 0.0:
        # En convention clockwise depuis le Nord :
        # convergence > 0 → Nord Lambert est à l'est → décaler vers l'ouest
        ax.set_theta_offset(math.radians(-convergence_deg))

    tf = np.linspace(0, 2 * math.pi, 300)
    ax.plot(tf, [5.0]  * 300, "k--", lw=0.8, alpha=0.35)
    ax.plot(tf, [10.0] * 300, "k-",  lw=1.0, alpha=0.45)

    statuts_vus = set()
    for s in sects_sc:
        tmin    = float(s["tmin"])
        tmax    = float(s["tmax"])
        couronne = s.get("couronne", "5-10km")
        is_proj  = s.get("is_projet", False)
        statut   = s.get("statut", "En service")
        r_in  = 0.0 if couronne == "0-5km" else 5.0
        r_out = 5.0 if couronne == "0-5km" else 10.0
        col   = COULEURS_STATUT.get("Projet") if is_proj \
                else COULEURS_STATUT.get(statut, "#74ADD1")
        alp   = 0.85 if is_proj else 0.62
        _dessiner_secteur(ax, tmin, tmax, r_in, r_out, col, alp)
        statuts_vus.add("Projet" if is_proj else statut)

    # Arc IER — depuis iv_tous_fus (clé sc_id+100) si disponible,
    # sinon recalcul depuis les secteurs
    iv_tous_fus = secteurs.get(scenario_id + 100, [])
    if iv_tous_fus:
        ier_s, ier_e, ier_l = _ier_depuis_iv_fus(iv_tous_fus)
    else:
        ier_s, ier_e, ier_l = _ier_depuis_secteurs(sects_sc)
    if ier_l > 5:
        _dessiner_secteur(ax, ier_s, ier_e, 0.0, 10.0, C_IER, 0.18)

    ax.plot(0, 0, "ko", ms=7, zorder=6)
    ax.annotate("PDV", (0, 0), textcoords="offset points",
                xytext=(6, 6), fontsize=7, color="#333")

    ax.set_rticks([5, 10])
    ax.set_yticklabels(["5 km", "10 km"], fontsize=8, color="#555")
    ax.set_rlabel_position(20)
    ax.set_thetagrids(range(0, 360, 30), fontsize=7, color="#777")
    ax.grid(True, alpha=0.18, lw=0.5)
    ax.set_ylim(0, 10.5)
    ax.set_title(
        f"{nom_projet}\n{sc_noms.get(scenario_id, f'Sc.{scenario_id}')}",
        fontsize=10, fontweight="bold", pad=15, color="#1A1A2E",
    )

    handles = []
    for stat, col in COULEURS_STATUT.items():
        if stat in statuts_vus:
            handles.append(mpatches.Patch(color=col, alpha=0.75, label=stat))
    ier_val = sc_data.get("IER", ier_l)
    handles.append(mpatches.Patch(color=C_IER, alpha=0.4,
                                   label=f"Espace de respiration ({ier_val:.1f}°)"))
    ax.legend(handles=handles, loc="lower left", fontsize=7,
              bbox_to_anchor=(-0.18, -0.05), framealpha=0.85)

    # ── Panneau indices ──────────────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[1])
    ax2.set_facecolor(GREY_BG)
    ax2.axis("off")

    sature   = (sc_data.get("alerte_IOH") or sc_data.get("alerte_ID1")
                or sc_data.get("alerte_ID2") or sc_data.get("alerte_IER"))
    verd_txt = "SATURATION" if sature else "CONFORME"
    verd_col = C_WARN if sature else C_OK
    ax2.text(0.5, 0.97, verd_txt, transform=ax2.transAxes,
             ha="center", va="top", fontsize=16,
             fontweight="bold", color=verd_col)
    ax2.text(0.5, 0.90, f"Indices DREAL HdF — Sc.{scenario_id}",
             transform=ax2.transAxes, ha="center", va="top",
             fontsize=9, color="#555")

    cfg = [
        ("IOH", SEUIL_IOH, "°",        "IOH — Occupation de l'horizon",   False),
        ("IOH_alt", SEUIL_IOH, "°",    "IOH alternatif (A + 0,5×A')",     False),
        ("IOH_net", SEUIL_IOH, "°",    "IOH net (A + A' – A'')",           False),
        ("ID1", SEUIL_ID1, " éol/°",   "ID1 — Densité horizon",            False),
        ("ID2_10km", SEUIL_ID2, " éol/km²", "ID2 — Densité surface (10km)", False),
        ("IER", SEUIL_IER, "°",        "IER — Espace de respiration",      True),
    ]
    y = 0.82
    for key, seuil, unite, libelle, inversé in cfg:
        val    = sc_data.get(key, 0.0)
        alerte = (val < seuil) if inversé else (val > seuil)
        bg     = "#FDECEA" if alerte else "#EAF7EE"
        ic     = C_WARN   if alerte else C_OK
        sym    = "!" if alerte else "v"
        rect   = mpatches.FancyBboxPatch(
            (0.02, y - 0.06), 0.96, 0.10,
            boxstyle="round,pad=0.01", lw=0,
            facecolor=bg, transform=ax2.transAxes, clip_on=False,
        )
        ax2.add_patch(rect)
        ax2.text(0.05, y - 0.01, libelle,
                 transform=ax2.transAxes, ha="left", va="center",
                 fontsize=7.5, color="#333")
        val_str = f"{val:.1f}{unite}" if key in ("IER","IOH","IOH_alt","IOH_net") \
                  else f"{val:.4f}{unite}"
        ax2.text(0.63, y - 0.01, val_str,
                 transform=ax2.transAxes, ha="left", va="center",
                 fontsize=9, fontweight="bold", color=ic)
        ax2.text(0.63, y - 0.055,
                 f"seuil : {'<' if inversé else '>'} {seuil}{unite}",
                 transform=ax2.transAxes, ha="left", va="center",
                 fontsize=6.5, color="#888")
        ax2.text(0.93, y - 0.01, sym,
                 transform=ax2.transAxes, ha="center", va="center",
                 fontsize=12, color=ic)
        y -= 0.115

    y -= 0.02
    for i, (k, lbl) in enumerate([
        ("B",  "Éoliennes 0–5 km (B)"),
        ("Bp", "Éoliennes 5–10 km (B')"),
        ("N",  "Total éoliennes (N)"),
    ]):
        ax2.text(0.05, y - i * 0.055, f"{lbl} : {int(sc_data.get(k, 0))}",
                 transform=ax2.transAxes, ha="left", va="top",
                 fontsize=8, color="#444")

    ax2.text(0.5, 0.01,
             f"Source : Saturation Visuelle DREAL — {nom_projet}\n"
             "Méthode DREAL Hauts-de-France, fév. 2024",
             transform=ax2.transAxes, ha="center", va="bottom",
             fontsize=6.5, color="#AAA", style="italic")

    nom_fichier = f"{nom_projet.replace(' ', '_')}_polaire_Sc{scenario_id}.png"
    chemin      = os.path.join(output_dir, nom_fichier)
    plt.savefig(chemin, dpi=180, bbox_inches="tight",
                facecolor=GREY_BG, edgecolor="none")
    plt.close(fig)
    return chemin


# ════════════════════════════════════════════════════════════════════════════
#  FIGURE 2 — Tableau de synthèse 4 scénarios × 6 indices
# ════════════════════════════════════════════════════════════════════════════

def _figure_synthese(resultats, nom_projet, output_dir):
    sc_ids = [1, 2, 3, 4]
    sc_labels = {
        1: "Sc.1\nEn service\n+ Autorisé",
        2: "Sc.2\n+ Projet",
        3: "Sc.3\n+ En instruction",
        4: "Sc.4\n+ En instruction\n+ Projet",
    }
    indices_ordre  = ["IOH", "IOH_alt", "IOH_net", "ID1", "ID2_10km", "IER"]
    indices_labels = {
        "IOH":      "IOH", "IOH_alt": "IOH alt.",
        "IOH_net":  "IOH net", "ID1": "ID1",
        "ID2_10km": "ID2 (10km)", "IER": "IER",
    }
    seuils_ref = {
        "IOH": 120, "IOH_alt": 120, "IOH_net": 120,
        "ID1": 0.1, "ID2_10km": 0.25, "IER": 160,
    }
    unites = {
        "IOH": "°", "IOH_alt": "°", "IOH_net": "°",
        "ID1": "", "ID2_10km": "", "IER": "°",
    }

    fig, axes = plt.subplots(
        1, 4, figsize=(18, 5),
        facecolor=GREY_BG,
        gridspec_kw={"wspace": 0.3},
    )
    fig.patch.set_facecolor(GREY_BG)

    for j, sc_id in enumerate(sc_ids):
        ax      = axes[j]
        sc_data = resultats.get(sc_id, {})
        sature  = (sc_data.get("alerte_IOH") or sc_data.get("alerte_ID1")
                   or sc_data.get("alerte_ID2") or sc_data.get("alerte_IER"))
        vc = C_WARN if sature else C_OK
        vt = "SATURATION" if sature else "CONFORME"
        bg = "#FFF5F5" if sature else "#F5FFF8"

        ax.set_facecolor(GREY_BG)
        ax.axis("off")
        ax.set_title(sc_labels[sc_id], fontsize=9,
                     fontweight="bold", color="#1A1A2E", pad=8)
        ax.add_patch(mpatches.FancyBboxPatch(
            (0.02, 0.02), 0.96, 0.96,
            boxstyle="round,pad=0.02", linewidth=1.5,
            edgecolor=vc, facecolor=bg,
            transform=ax.transAxes, clip_on=False,
        ))
        ax.text(0.5, 0.94, vt, transform=ax.transAxes,
                ha="center", va="top", fontsize=9,
                fontweight="bold", color=vc)

        y_pos = 0.80
        for idx_key in indices_ordre:
            val    = sc_data.get(idx_key, 0.0)
            seuil  = seuils_ref[idx_key]
            unite  = unites[idx_key]
            is_ier = idx_key == "IER"
            alerte = (val < seuil) if is_ier else (val > seuil)
            col    = C_WARN if alerte else "#444"
            sym    = "!" if alerte else " "
            val_str = (f"{val:.1f}{unite}"
                       if idx_key in ("IER","IOH","IOH_alt","IOH_net")
                       else f"{val:.3f}")
            ax.text(0.06, y_pos, indices_labels[idx_key],
                    transform=ax.transAxes, ha="left", va="center",
                    fontsize=7.5, color="#666")
            ax.text(0.65, y_pos, val_str,
                    transform=ax.transAxes, ha="right", va="center",
                    fontsize=8, fontweight="bold", color=col)
            ax.text(0.95, y_pos, sym,
                    transform=ax.transAxes, ha="right", va="center",
                    fontsize=9, color=col)
            y_pos -= 0.135

    fig.suptitle(
        f"Synthèse Saturation Visuelle — {nom_projet}\n"
        "Méthode DREAL Hauts-de-France (fév. 2024)",
        fontsize=12, fontweight="bold", color="#1A1A2E", y=1.03,
    )
    fig.text(
        0.99, -0.02,
        f"Source : Saturation Visuelle DREAL — {nom_projet} | DREAL HdF fév. 2024",
        ha="right", va="bottom", fontsize=6.5, color="#AAA", style="italic",
    )

    nom_fichier = f"{nom_projet.replace(' ', '_')}_synthese.png"
    chemin      = os.path.join(output_dir, nom_fichier)
    plt.savefig(chemin, dpi=180, bbox_inches="tight",
                facecolor=GREY_BG, edgecolor="none")
    plt.close(fig)
    return chemin


# ════════════════════════════════════════════════════════════════════════════
#  POINT D'ENTRÉE PRINCIPAL
# ════════════════════════════════════════════════════════════════════════════

def generer_figures(resultats, secteurs, iv_tous_par_sc,
                    output_dir, nom_projet="Projet",
                    x_obs=None, y_obs=None):
    """
    Génère 4 figures polaires (une par scénario) + 1 tableau de synthèse.

    :param resultats:       dict {sc_id: {IOH, IER, ID1, ID2_10km, alerte_*, ...}}
    :param secteurs:        dict {sc_id: [{"tmin","tmax","couronne","statut",
                                           "parc","is_projet"}, ...]}
    :param iv_tous_par_sc:  dict {sc_id: [(tmin, tmax), ...]} — intervalles fusionnés
                            pour le tracé exact de l'arc IER
    :param output_dir:      str  dossier de sortie
    :param nom_projet:      str  nom affiché dans les titres et noms de fichiers
    :returns: (chemins_polaires, chemin_synthese) ou ([], None) si matplotlib absent
    """
    if not MPL_OK:
        return [], None

    os.makedirs(output_dir, exist_ok=True)

    # Injecter iv_tous_fus dans le dict secteurs pour chaque scénario
    secteurs_complets = dict(secteurs)
    for sc_id, iv in (iv_tous_par_sc or {}).items():
        secteurs_complets[sc_id + 100] = iv

    # Convergence des méridiens pour orientation correcte du graphique
    convergence_deg = 0.0
    if x_obs is not None and y_obs is not None:
        convergence_deg = _convergence_lambert93(x_obs, y_obs)

    chemins_polaires = []
    for sc_id in sorted(resultats.keys()):
        chemin = _figure_polaire(
            resultats, secteurs_complets, sc_id, nom_projet, output_dir,
            convergence_deg=convergence_deg,
        )
        chemins_polaires.append(chemin)

    chemin_synthese = _figure_synthese(resultats, nom_projet, output_dir)

    return chemins_polaires, chemin_synthese
