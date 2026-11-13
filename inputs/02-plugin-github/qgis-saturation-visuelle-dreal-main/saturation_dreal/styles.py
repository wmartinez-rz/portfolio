# -*- coding: utf-8 -*-
"""
styles.py — Application des styles QGIS pour la saturation visuelle.

Deux fonctions :
  1. creer_couche_anneaux()  — génère les anneaux 0–5 km et 5–10 km
                               comme couche vectorielle temporaire
  2. appliquer_style_wedges() — applique un style catégorisé par statut
                                 sur la couche wedges

Appelées depuis processAlgorithm après la génération des couches.
"""

import os
import math

from qgis.core import (
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsFields,
    QgsField,
    QgsProject,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant

from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsRendererCategory,
    QgsFillSymbol,
    QgsSimpleFillSymbolLayer,
    QgsLineSymbol,
    QgsSimpleLineSymbolLayer,
)
from qgis.PyQt.QtGui import QColor


# ── Palette conforme DREAL ───────────────────────────────────────────────────
STYLES_STATUT = {
    "En service":     {"fill": "#2C7BB6", "alpha": 0.65, "border": "#1A5F8A"},
    "Autorisé":       {"fill": "#74ADD1", "alpha": 0.65, "border": "#4A7FA0"},
    "En instruction": {"fill": "#ABD9E9", "alpha": 0.65, "border": "#7AAECC"},
    "Projet":         {"fill": "#E8533F", "alpha": 0.80, "border": "#C03020"},
    "IER":            {"fill": "#2ECC71", "alpha": 0.20, "border": "#27AE60"},
}


# ════════════════════════════════════════════════════════════════════════════
#  Couche anneaux 0–5 km / 5–10 km
# ════════════════════════════════════════════════════════════════════════════

def creer_couche_anneaux(x_obs, y_obs, crs_authid="EPSG:2154",
                          n_pts=180, ajouter_qgis=True):
    """
    Crée une couche vectorielle temporaire avec deux polygones :
      - Anneau intérieur : cercle de 5 000 m (rayon DREAL)
      - Anneau extérieur : cercle de 10 000 m (rayon DREAL)

    :param x_obs:      coordonnée X du point de vue (m)
    :param y_obs:      coordonnée Y du point de vue (m)
    :param crs_authid: identifiant CRS (défaut EPSG:2154)
    :param n_pts:      nombre de points pour les cercles (défaut 180)
    :param ajouter_qgis: si True, ajoute la couche au projet QGIS courant
    :returns: QgsVectorLayer ou None en cas d'erreur
    """

    def _cercle(cx, cy, rayon):
        pts = []
        for i in range(n_pts + 1):
            angle = 2 * math.pi * i / n_pts
            pts.append(QgsPointXY(
                cx + rayon * math.sin(angle),
                cy + rayon * math.cos(angle),
            ))
        return pts

    uri    = f"Polygon?crs={crs_authid}"
    couche = QgsVectorLayer(uri, "Couronnes DREAL (5 km / 10 km)", "memory")
    prov   = couche.dataProvider()

    champs = QgsFields()
    champs.append(QgsField("rayon_km", QVariant.Int))
    champs.append(QgsField("libelle",  QVariant.String, len=30))
    prov.addAttributes(champs)
    couche.updateFields()

    features = []
    for rayon_m, libelle in [(5_000, "0–5 km"), (10_000, "5–10 km")]:
        pts  = _cercle(x_obs, y_obs, rayon_m)
        geom = QgsGeometry.fromPolygonXY([pts])
        feat = QgsFeature()
        feat.setGeometry(geom)
        feat.setAttributes([rayon_m // 1000, libelle])
        features.append(feat)
    prov.addFeatures(features)
    couche.updateExtents()

    # Style : contours noirs pointillés, pas de remplissage
    _appliquer_style_anneaux(couche)

    if ajouter_qgis:
        QgsProject.instance().addMapLayer(couche)

    return couche


def _appliquer_style_anneaux(couche):
    """Style sobre : pas de remplissage, contour noir pointillé."""
    try:
        symbol = QgsFillSymbol.createSimple({
            "color":         "0,0,0,0",
            "outline_color": "#1A1A1A",
            "outline_style": "dash",
            "outline_width": "0.5",
        })
        couche.renderer().setSymbol(symbol)
        couche.triggerRepaint()
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════════════
#  Style catégorisé sur la couche wedges
# ════════════════════════════════════════════════════════════════════════════

def appliquer_style_wedges(couche_wedges):
    """
    Applique un style catégorisé par champ 'type_arc' sur la couche wedges.

    Catégories gérées : "occupe" (secteurs occupés par statut via
    le champ 'statuts') et "IER" (arc de respiration en vert).

    Note : la couche wedges du plugin utilise le champ 'type_arc'
    (valeurs : "occupe" ou "IER") et 'statuts' (valeurs DREAL).
    Le style catégorisé ici est basé sur 'type_arc' pour distinguer
    visuellement les deux types de wedges.
    """
    if couche_wedges is None or not couche_wedges.isValid():
        return

    categories = []

    # Catégorie "occupe" — couleur par defaut (bleu institutionnel)
    sym_occupe = QgsFillSymbol.createSimple({
        "color":         "44,123,182,165",
        "outline_color": "#1A5F8A",
        "outline_style": "solid",
        "outline_width": "0.3",
    })
    categories.append(QgsRendererCategory("occupe", sym_occupe, "Secteur occupé"))

    # Catégorie "IER" — vert semi-transparent
    sym_ier = QgsFillSymbol.createSimple({
        "color":         "46,204,113,50",
        "outline_color": "#27AE60",
        "outline_style": "solid",
        "outline_width": "0.5",
    })
    categories.append(QgsRendererCategory("IER", sym_ier, "Espace de respiration (IER)"))

    renderer = QgsCategorizedSymbolRenderer("type_arc", categories)
    couche_wedges.setRenderer(renderer)
    couche_wedges.triggerRepaint()


# ════════════════════════════════════════════════════════════════════════════
#  Nommage standardisé des couches dans QGIS
# ════════════════════════════════════════════════════════════════════════════

def renommer_couches_qgis(nom_projet, dest_wedge_id=None, dest_pts_id=None):
    """
    Renomme les couches wedges et points dans le projet QGIS courant
    pour une identification claire dans le panneau couches.
    """
    projet = QgsProject.instance()

    if dest_wedge_id:
        couche = projet.mapLayer(dest_wedge_id)
        if couche:
            couche.setName(f"Saturation — Secteurs angulaires ({nom_projet})")

    if dest_pts_id:
        couche = projet.mapLayer(dest_pts_id)
        if couche:
            couche.setName(f"Saturation — Éoliennes filtrées ({nom_projet})")
