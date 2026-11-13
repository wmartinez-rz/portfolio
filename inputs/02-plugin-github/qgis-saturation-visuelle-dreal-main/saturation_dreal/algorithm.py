# -*- coding: utf-8 -*-
"""
algorithm.py — Algorithme principal de saturation visuelle DREAL HdF.
Version 3 — Calcul trigonométrique conditionnel du rotor + export CSV Excel.

Nouveautés v3 :
  - Deux paramètres optionnels pour le diamètre du rotor :
      * DIAMETRE_ROTOR_GLOBAL : valeur numérique unique pour toutes les éoliennes
      * FIELD_DIAMETRE_ROTOR  : champ attributaire par éolienne (prioritaire)
  - Hiérarchie de priorité par entité :
      1. Valeur du champ attributaire (si valide > 0)
      2. Valeur globale (si > 0)
      3. None → math_utils applique le fallback institutionnel (120 m isolée /
         centro-à-centro multi-mâts)
  - Export CSV matriciel (4 lignes × 15 colonnes) compatible Excel Europe :
      * Séparateur point-virgule
      * Encodage utf-8-sig (BOM Windows)
      * Décimales avec virgule

Scénarios DREAL (PDF fév. 2024) :
  Sc.1 : En service + Autorisé
  Sc.2 : Sc.1 + Projet (couche séparée)
  Sc.3 : Sc.1 + En instruction
  Sc.4 : Sc.3 + Projet (couche séparée)
"""

import math
import csv
import io
import os

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFolderDestination,
    QgsProcessingOutputFolder,
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsProcessingOutputString,
    QgsWkbTypes,
    QgsFields,
    QgsField,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsCoordinateTransform,
    QgsProject,
    QgsProcessing,
    QgsProcessingException,
)
from qgis.PyQt.QtCore import QVariant

from .math_utils import (
    calcul_azimut,
    distance_plane,
    cone_parc_avec_rotor,
    normaliser_intervalle,
    fusionner_intervalles,
    somme_angles,
    intersection_intervalles,
    calculer_ier,
    generer_wedge_qgs,
    RAYON_INTERNE_M,
    RAYON_EXTERNE_M,
)

# ---------------------------------------------------------------------------
# Statuts reconnus dans la couche inventaire globale
# ---------------------------------------------------------------------------
STATUTS_VALIDES = ["Autorisé", "En service", "En instruction"]
STATUT_PROJET   = "Projet"

# ---------------------------------------------------------------------------
# Seuils d'alerte DREAL (PDF p.4)
# ---------------------------------------------------------------------------
SEUIL_IOH_DEG  = 120.0
SEUIL_ID1      = 0.1
SEUIL_ID2_KM2  = 0.25
SEUIL_IER_DEG  = 160.0

# Surfaces des disques (km²)
SURFACE_5KM_KM2  = math.pi * (RAYON_INTERNE_M  / 1_000.0) ** 2  # ≈  78.54
SURFACE_10KM_KM2 = math.pi * (RAYON_EXTERNE_M  / 1_000.0) ** 2  # ≈ 314.16

# ---------------------------------------------------------------------------
# 4 scénarios réglementaires DREAL
# ---------------------------------------------------------------------------
SCENARIOS = [
    {
        "id": 1,
        "nom": "Scénario 1 — En service + Autorisé",
        "statuts_inventaire": ["En service", "Autorisé"],
        "inclure_projet": False,
    },
    {
        "id": 2,
        "nom": "Scénario 2 — En service + Autorisé + Projet",
        "statuts_inventaire": ["En service", "Autorisé"],
        "inclure_projet": True,
    },
    {
        "id": 3,
        "nom": "Scénario 3 — En service + Autorisé + En instruction",
        "statuts_inventaire": ["En service", "Autorisé", "En instruction"],
        "inclure_projet": False,
    },
    {
        "id": 4,
        "nom": "Scénario 4 — En service + Autorisé + En instruction + Projet",
        "statuts_inventaire": ["En service", "Autorisé", "En instruction"],
        "inclure_projet": True,
    },
]

# En-tête CSV exacte demandée
CSV_ENTETE = [
    "Scenario_ID", "Scenario_Nom",
    "A_deg", "Ap_deg", "App_deg",
    "IOH_brut", "IOH_alt", "IOH_net",
    "B_eol", "Bp_eol", "N_eol",
    "ID1", "ID2_5km", "ID2_10km", "IER_deg",
]


# ===========================================================================
# Algorithme principal
# ===========================================================================

class SaturationDrealAlgorithm(QgsProcessingAlgorithm):
    """
    Calcule la saturation visuelle éolienne selon la méthode DREAL HdF (fév. 2024).
    """

    # Identifiants des paramètres
    INPUT_POINT           = "INPUT_POINT"
    INPUT_EOLIENNES       = "INPUT_EOLIENNES"
    FIELD_STATUT          = "FIELD_STATUT"
    FIELD_PARC            = "FIELD_PARC"
    DIAMETRE_ROTOR_GLOBAL = "DIAMETRE_ROTOR_GLOBAL"
    FIELD_DIAMETRE_ROTOR  = "FIELD_DIAMETRE_ROTOR"
    INPUT_PROJET          = "INPUT_PROJET"
    FIELD_PARC_PROJ       = "FIELD_PARC_PROJ"
    OUTPUT_DIR    = "OUTPUT_DIR"
    NOM_PROJET    = "NOM_PROJET"
    OUTPUT_RAPPORT = "OUTPUT_RAPPORT"

    def __init__(self):
        super().__init__()

    # -----------------------------------------------------------------------
    # Métadonnées
    # -----------------------------------------------------------------------

    def name(self):
        return "saturation_visuelle_dreal"

    def displayName(self):
        return "Saturation Visuelle DREAL HdF"

    def group(self):
        return "Analyse Éolienne"

    def groupId(self):
        return "analyse_eolienne"

    def shortHelpString(self):
        return (
            "<b>Saturation Visuelle Éolienne — Méthode DREAL HdF (fév. 2024) v3</b><br><br>"
            "<b>Diamètre du rotor (priorité) :</b><br>"
            "1. Champ attributaire par éolienne (si valide > 0)<br>"
            "2. Valeur globale saisie dans le formulaire (si > 0)<br>"
            "3. Fallback automatique : 120 m (isolée) / centro-à-centro (multi-mâts)<br><br>"
            "<b>Sorties :</b> wedges polygones · points éoliennes · rapport · CSV Excel"
        )

    def createInstance(self):
        return SaturationDrealAlgorithm()

    def postProcessAlgorithm(self, context, feedback):
        """
        Hook appelé par QGIS après le chargement des couches de sortie.
        Applique les styles catégorisés sur la couche wedges.
        """
        try:
            from .styles import appliquer_style_wedges
            from qgis.core import QgsProject
            for layer in QgsProject.instance().mapLayers().values():
                if "Saturation" in (layer.name() or "") and "Secteurs" in (layer.name() or ""):
                    appliquer_style_wedges(layer)
                    feedback.pushInfo(f"  Style wedges appliqué : {layer.name()}")
        except Exception:
            pass
        return {}

    # -----------------------------------------------------------------------
    # Déclaration des paramètres
    # -----------------------------------------------------------------------

    def initAlgorithm(self, config=None):

        # --- Lieu de vie ---
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_POINT,
            "Lieu de vie (point d'observation unique)",
            [QgsProcessing.TypeVectorPoint],
        ))

        # --- Inventaire éoliennes ---
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_EOLIENNES,
            "Inventaire éoliennes (Autorisé / En service / En instruction)",
            [QgsProcessing.TypeVectorPoint],
        ))

        self.addParameter(QgsProcessingParameterField(
            self.FIELD_STATUT,
            "Champ : Statut réglementaire",
            parentLayerParameterName=self.INPUT_EOLIENNES,
            type=QgsProcessingParameterField.String,
        ))

        self.addParameter(QgsProcessingParameterField(
            self.FIELD_PARC,
            "Champ : Nom du parc (inventaire)",
            parentLayerParameterName=self.INPUT_EOLIENNES,
            type=QgsProcessingParameterField.String,
        ))

        # --- Diamètre du rotor : valeur globale (optionnel) ---
        param_diam_global = QgsProcessingParameterNumber(
            self.DIAMETRE_ROTOR_GLOBAL,
            "Diamètre du rotor global (m) — optionnel",
            type=QgsProcessingParameterNumber.Double,
            minValue=0.0,
            defaultValue=0.0,
            optional=True,
        )
        param_diam_global.setFlags(
            param_diam_global.flags() | QgsProcessingParameterNumber.FlagOptional
        )
        self.addParameter(param_diam_global)

        # --- Diamètre du rotor : champ attributaire (optionnel, prioritaire) ---
        param_diam_champ = QgsProcessingParameterField(
            self.FIELD_DIAMETRE_ROTOR,
            "Champ : Diamètre du rotor (table, prioritaire sur la valeur globale)",
            parentLayerParameterName=self.INPUT_EOLIENNES,
            type=QgsProcessingParameterField.Numeric,
            optional=True,
        )
        self.addParameter(param_diam_champ)

        # --- Couche projet propre (optionnel) ---
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_PROJET,
            "Éoliennes du projet propre (couche séparée, optionnel)",
            [QgsProcessing.TypeVectorPoint],
            optional=True,
        ))

        self.addParameter(QgsProcessingParameterField(
            self.FIELD_PARC_PROJ,
            "Champ : Nom du parc (projet propre)",
            parentLayerParameterName=self.INPUT_PROJET,
            type=QgsProcessingParameterField.String,
            optional=True,
        ))

        # --- Nom du projet ---
        from qgis.core import QgsProcessingParameterString
        self.addParameter(QgsProcessingParameterString(
            self.NOM_PROJET,
            "Nom du projet (affiché dans les titres et noms de fichiers)",
            defaultValue="Projet",
            optional=False,
        ))

        # --- Dossier de sortie unique ---
        self.addParameter(QgsProcessingParameterFolderDestination(
            self.OUTPUT_DIR,
            "Dossier de sortie (structure créée automatiquement)",
        ))

        # --- Rapport textuel ---
        self.addOutput(QgsProcessingOutputString(
            self.OUTPUT_RAPPORT,
            "Rapport des indices DREAL",
        ))
        self.addOutput(QgsProcessingOutputFolder(
            self.OUTPUT_DIR,
            "Dossier de sortie",
        ))

    # -----------------------------------------------------------------------
    # Corps principal
    # -----------------------------------------------------------------------

    def processAlgorithm(self, parameters, context, feedback):

        # -------------------------------------------------------------------
        # 1. Lecture des paramètres
        # -------------------------------------------------------------------
        couche_obs      = self.parameterAsVectorLayer(parameters, self.INPUT_POINT, context)
        couche_eol      = self.parameterAsVectorLayer(parameters, self.INPUT_EOLIENNES, context)
        champ_statut    = self.parameterAsString(parameters, self.FIELD_STATUT, context)
        champ_parc      = self.parameterAsString(parameters, self.FIELD_PARC, context)
        couche_projet   = self.parameterAsVectorLayer(parameters, self.INPUT_PROJET, context)
        champ_parc_proj = self.parameterAsString(parameters, self.FIELD_PARC_PROJ, context)
        nom_projet  = self.parameterAsString(parameters, self.NOM_PROJET, context) or "Projet"
        output_dir  = self.parameterAsString(parameters, self.OUTPUT_DIR, context)
        nom_safe    = nom_projet.replace(" ", "_")

        # --- Arborescence de sortie ---
        dir_vecteurs = os.path.join(output_dir, "1_Vecteurs")
        dir_figures  = os.path.join(output_dir, "2_Figures")
        os.makedirs(dir_vecteurs, exist_ok=True)
        os.makedirs(dir_figures,  exist_ok=True)

        chemin_wedges  = os.path.join(dir_vecteurs, f"{nom_safe}_wedges.gpkg")
        chemin_pts     = os.path.join(dir_vecteurs, f"{nom_safe}_eoliennes.gpkg")
        chemin_csv     = os.path.join(output_dir,  f"{nom_safe}_resultats.csv")
        chemin_rapport = os.path.join(output_dir,  f"{nom_safe}_rapport.txt")
        dossier_figures = dir_figures

        # Diamètre du rotor global (0.0 = non fourni)
        diam_global = self.parameterAsDouble(parameters, self.DIAMETRE_ROTOR_GLOBAL, context)
        if diam_global is None or diam_global <= 0:
            diam_global = None

        # Nom du champ diamètre (None si non fourni)
        champ_diam = self.parameterAsString(parameters, self.FIELD_DIAMETRE_ROTOR, context)
        if not champ_diam:
            champ_diam = None

        if couche_obs is None or couche_eol is None:
            raise QgsProcessingException("Couches d'entrée invalides ou manquantes.")
        if couche_obs.featureCount() != 1:
            raise QgsProcessingException(
                f"La couche 'Lieu de vie' doit contenir exactement 1 point "
                f"({couche_obs.featureCount()} trouvé(s))."
            )

        # -------------------------------------------------------------------
        # 2. Point d'observation
        # -------------------------------------------------------------------
        feature_obs  = next(couche_obs.getFeatures())
        pt_obs       = feature_obs.geometry().asPoint()
        x_obs, y_obs = pt_obs.x(), pt_obs.y()
        scr_ref      = couche_obs.crs()

        if not scr_ref.isValid():
            raise QgsProcessingException("Le SCR de la couche 'Lieu de vie' est invalide.")

        feedback.pushInfo(f"SCR de référence : {scr_ref.authid()}")
        feedback.pushInfo(f"Lieu de vie : X={x_obs:.2f} m | Y={y_obs:.2f} m")

        # Log de la stratégie rotor
        if champ_diam:
            feedback.pushInfo(
                f"Rotor : champ attributaire '{champ_diam}' (prioritaire)"
                + (f" | global = {diam_global} m (fallback)" if diam_global else " | fallback = 120 m (isolée)")
            )
        elif diam_global:
            feedback.pushInfo(f"Rotor : valeur globale = {diam_global} m")
        else:
            feedback.pushInfo(
                "Rotor : aucune valeur fournie → 120 m pour les isolées, "
                "centro-à-centro pour les parcs multi-mâts."
            )

        # -------------------------------------------------------------------
        # 3. Transformateurs de coordonnées
        # -------------------------------------------------------------------
        def _get_transform(couche):
            if couche is None:
                return None
            if couche.crs() != scr_ref:
                feedback.pushInfo(
                    f"Reprojection '{couche.name()}' : "
                    f"{couche.crs().authid()} → {scr_ref.authid()}"
                )
                return QgsCoordinateTransform(couche.crs(), scr_ref, QgsProject.instance())
            return None

        transf_eol  = _get_transform(couche_eol)
        transf_proj = _get_transform(couche_projet)

        # -------------------------------------------------------------------
        # 4. Extraction de l'inventaire avec résolution du diamètre par entité
        # -------------------------------------------------------------------
        eolienne_data   = []
        nb_statut_exclu = 0
        nb_hors_rayon   = 0

        for feat in couche_eol.getFeatures():
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue

            # Normalisation du statut
            statut_brut = str(feat[champ_statut]).strip() if feat[champ_statut] is not None else ""
            statut      = _normaliser_statut(statut_brut)
            if statut not in STATUTS_VALIDES:
                nb_statut_exclu += 1
                continue

            # Reprojection
            pt = geom.asPoint()
            if transf_eol is not None:
                pt = transf_eol.transform(pt)
            x_e, y_e = pt.x(), pt.y()

            dist = distance_plane(x_obs, y_obs, x_e, y_e)
            if dist > RAYON_EXTERNE_M:
                nb_hors_rayon += 1
                continue

            az   = calcul_azimut(x_obs, y_obs, x_e, y_e)
            parc = str(feat[champ_parc]).strip() if feat[champ_parc] is not None else "Inconnu"

            # ----------------------------------------------------------------
            # Résolution du diamètre du rotor pour cette entité
            # Priorité : 1) champ attributaire  2) global  3) None (fallback)
            # ----------------------------------------------------------------
            diam_entite = _resoudre_diametre(feat, champ_diam, diam_global)

            eolienne_data.append({
                "x": x_e, "y": y_e,
                "az": az, "dist": dist,
                "parc": parc,
                "statut": statut,
                "source": "inventaire",
                "diametre_m": diam_entite,   # None si aucune valeur disponible
            })

        feedback.pushInfo(
            f"Inventaire → {len(eolienne_data)} éolienne(s) retenue(s) "
            f"({nb_statut_exclu} statut(s) exclu(s), {nb_hors_rayon} hors 10 km)."
        )

        # -------------------------------------------------------------------
        # 5. Extraction de la couche projet propre
        # -------------------------------------------------------------------
        eol_projet   = []
        nb_proj_hors = 0

        if couche_projet is not None:
            for feat in couche_projet.getFeatures():
                geom = feat.geometry()
                if geom is None or geom.isEmpty():
                    continue
                pt = geom.asPoint()
                if transf_proj is not None:
                    pt = transf_proj.transform(pt)
                x_e, y_e = pt.x(), pt.y()

                dist = distance_plane(x_obs, y_obs, x_e, y_e)
                if dist > RAYON_EXTERNE_M:
                    nb_proj_hors += 1
                    continue

                az   = calcul_azimut(x_obs, y_obs, x_e, y_e)
                parc = (
                    str(feat[champ_parc_proj]).strip()
                    if champ_parc_proj
                    and feat.fields().indexOf(champ_parc_proj) >= 0
                    and feat[champ_parc_proj] is not None
                    else "Projet"
                )
                # Même résolution du diamètre pour le projet
                diam_entite = _resoudre_diametre(feat, champ_diam, diam_global)

                eol_projet.append({
                    "x": x_e, "y": y_e,
                    "az": az, "dist": dist,
                    "parc": parc,
                    "statut": STATUT_PROJET,
                    "source": "projet",
                    "diametre_m": diam_entite,
                })

            feedback.pushInfo(
                f"Projet propre → {len(eol_projet)} éolienne(s) retenue(s) "
                f"({nb_proj_hors} hors 10 km)."
            )
        else:
            feedback.pushInfo(
                "Aucune couche projet. Scénarios 2 et 4 identiques à 1 et 3."
            )

        # -------------------------------------------------------------------
        # 6 + 7. Champs des couches vectorielles (export GPKG en fin)
        # -------------------------------------------------------------------
        champs_wedge = QgsFields()
        champs_wedge.append(QgsField("scenario_id",   QVariant.Int,    len=2))
        champs_wedge.append(QgsField("scenario_nom",  QVariant.String, len=100))
        champs_wedge.append(QgsField("couronne",      QVariant.String, len=10))
        champs_wedge.append(QgsField("type_arc",      QVariant.String, len=20))
        champs_wedge.append(QgsField("statuts",       QVariant.String, len=120))
        champs_wedge.append(QgsField("az_debut_deg",  QVariant.Double, len=10, prec=4))
        champs_wedge.append(QgsField("az_fin_deg",    QVariant.Double, len=10, prec=4))
        champs_wedge.append(QgsField("amplitude_deg", QVariant.Double, len=10, prec=4))

        champs_pts = QgsFields()
        champs_pts.append(QgsField("parc",       QVariant.String, len=80))
        champs_pts.append(QgsField("statut",     QVariant.String, len=40))
        champs_pts.append(QgsField("source",     QVariant.String, len=20))
        champs_pts.append(QgsField("distance_m", QVariant.Double, len=12, prec=1))
        champs_pts.append(QgsField("azimut_deg", QVariant.Double, len=10, prec=4))
        champs_pts.append(QgsField("couronne",   QVariant.String, len=10))
        champs_pts.append(QgsField("diametre_m", QVariant.Double, len=8,  prec=1))

        # Listes en mémoire — export GPKG groupé en fin de processAlgorithm
        feats_wedge = []
        feats_pts   = []

        for e in (eolienne_data + eol_projet):
            couronne = "0-5km" if e["dist"] < RAYON_INTERNE_M else "5-10km"
            feat_pt  = QgsFeature(champs_pts)
            feat_pt.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(e["x"], e["y"])))
            feat_pt.setAttributes([
                e["parc"], e["statut"], e["source"],
                round(e["dist"], 1), round(e["az"], 4),
                couronne,
                round(e["diametre_m"], 1) if e["diametre_m"] else None,
            ])
            feats_pts.append(feat_pt)

        # -------------------------------------------------------------------
        # 8. Boucle principale — 4 scénarios
        # -------------------------------------------------------------------
        resultats = {}
        # Secteurs par scénario — alimentés dans la boucle pour les figures
        secteurs_figures = {}
        iv_tous_par_sc   = {}  # iv_tous_fus par sc_id pour IER exact

        for idx_sc, scenario in enumerate(SCENARIOS):
            if feedback.isCanceled():
                break

            feedback.setProgress(int(idx_sc / len(SCENARIOS) * 85))

            sc_id          = scenario["id"]
            sc_nom         = scenario["nom"]
            statuts_inv    = scenario["statuts_inventaire"]
            inclure_projet = scenario["inclure_projet"]

            feedback.pushInfo(f"\n{'='*60}\n{sc_nom}")

            # Pool d'éoliennes du scénario
            pool = [e for e in eolienne_data if e["statut"] in statuts_inv]
            if inclure_projet:
                pool = pool + eol_projet

            # ---------------------------------------------------------------
            # 8a. Intervalles par couronne (avec rotor conditionnel)
            #     La variante _avec_secteurs retourne aussi les arcs
            #     par parc pour les graphiques polaires — même logique
            #     exacte que l'original (1 appel par parc, pas par mât)
            # ---------------------------------------------------------------
            iv_5km,  sects_5km  = _construire_intervalles_avec_secteurs(
                pool, x_obs, y_obs, 0.0, RAYON_INTERNE_M, "0-5km"
            )
            iv_10km, sects_10km = _construire_intervalles_avec_secteurs(
                pool, x_obs, y_obs, RAYON_INTERNE_M, RAYON_EXTERNE_M, "5-10km"
            )

            # Secteurs complets pour les figures (5km + 10km)
            if dossier_figures:
                secteurs_figures[sc_id] = sects_5km + sects_10km

            # ---------------------------------------------------------------
            # 8b. A, A', A''
            # ---------------------------------------------------------------
            A   = somme_angles(iv_5km)
            Ap  = somme_angles(iv_10km)
            App = somme_angles(intersection_intervalles(iv_5km, iv_10km))

            # ---------------------------------------------------------------
            # 8c. Indices DREAL
            # ---------------------------------------------------------------
            IOH     = A + Ap
            IOH_alt = A + 0.5 * Ap
            IOH_net = A + Ap - App

            B  = sum(1 for e in pool if e["dist"] < RAYON_INTERNE_M)
            Bp = sum(1 for e in pool if RAYON_INTERNE_M <= e["dist"] < RAYON_EXTERNE_M)
            N  = B + Bp

            ID1      = B / IOH if IOH > 0 else 0.0
            ID2_5km  = B / SURFACE_5KM_KM2  if SURFACE_5KM_KM2  > 0 else 0.0
            ID2_10km = N / SURFACE_10KM_KM2 if SURFACE_10KM_KM2 > 0 else 0.0

            iv_tous = fusionner_intervalles(iv_5km + iv_10km)
            IER     = calculer_ier(iv_tous)

            # Stocker iv_tous_fus pour l'IER exact dans les figures
            if dossier_figures:
                iv_tous_par_sc[sc_id] = iv_tous

            alerte_IOH = IOH      > SEUIL_IOH_DEG
            alerte_ID1 = ID1      > SEUIL_ID1
            alerte_ID2 = ID2_10km > SEUIL_ID2_KM2
            alerte_IER = IER      < SEUIL_IER_DEG

            resultats[sc_id] = {
                "nom":       sc_nom,
                "A": A,      "Ap": Ap,     "App": App,
                "IOH": IOH,  "IOH_alt": IOH_alt, "IOH_net": IOH_net,
                "B": B,      "Bp": Bp,     "N": N,
                "ID1": ID1,
                "ID2_5km": ID2_5km, "ID2_10km": ID2_10km,
                "IER": IER,
                "alerte_IOH": alerte_IOH,
                "alerte_ID1": alerte_ID1,
                "alerte_ID2": alerte_ID2,
                "alerte_IER": alerte_IER,
            }

            # ---------------------------------------------------------------
            # 8d. Écriture des wedges
            # ---------------------------------------------------------------
            statuts_str = ", ".join(
                statuts_inv + ([STATUT_PROJET] if inclure_projet else [])
            )
            self._ecrire_wedges(
                feats_wedge, iv_5km,  sc_id, sc_nom, "0-5km",
                x_obs, y_obs, 0.0, RAYON_INTERNE_M, statuts_str, "occupe",
                champs_wedge,
            )
            self._ecrire_wedges(
                feats_wedge, iv_10km, sc_id, sc_nom, "5-10km",
                x_obs, y_obs, RAYON_INTERNE_M, RAYON_EXTERNE_M, statuts_str, "occupe",
                champs_wedge,
            )
            ier_iv = self._trouver_arc_vide_dominant(iv_tous, IER)
            if ier_iv is not None:
                self._ecrire_wedge_unique(
                    feats_wedge, ier_iv[0], ier_iv[1],
                    sc_id, sc_nom, "0-10km",
                    x_obs, y_obs, 0.0, RAYON_EXTERNE_M, statuts_str, "IER",
                    champs_wedge,
                )

            # Log résumé
            feedback.pushInfo(
                f"  A={A:.1f}° A'={Ap:.1f}° A''={App:.1f}°\n"
                f"  IOH={IOH:.1f}° (alt={IOH_alt:.1f}°, net={IOH_net:.1f}°)\n"
                f"  B={B} B'={Bp} N={N}\n"
                f"  ID1={ID1:.4f} éol/° | ID2(5)={ID2_5km:.4f} | ID2(10)={ID2_10km:.4f} éol/km²\n"
                f"  IER={IER:.1f}°\n"
                f"  Alertes → IOH:{'⚠' if alerte_IOH else '✓'} "
                f"ID1:{'⚠' if alerte_ID1 else '✓'} "
                f"ID2:{'⚠' if alerte_ID2 else '✓'} "
                f"IER:{'⚠' if alerte_IER else '✓'}"
            )

        # -------------------------------------------------------------------
        # 9. Rapport textuel
        # -------------------------------------------------------------------
        rapport = self._generer_rapport(resultats)
        feedback.pushInfo(rapport)

        # -------------------------------------------------------------------
        # 10. Export CSV (utf-8-sig, point-virgule, virgule décimale)
        # -------------------------------------------------------------------
        if chemin_csv:
            self._exporter_csv(resultats, chemin_csv, feedback)

        feedback.setProgress(98)

        # -------------------------------------------------------------------
        # 11. Génération des figures PNG (polaire + synthèse)
        # -------------------------------------------------------------------
        chemin_polaire  = ""
        chemin_synthese = ""

        if dossier_figures:
            try:
                from .figures import generer_figures
                feedback.pushInfo("\nGénération des figures PNG...")
                chemins_polaires, chemin_synthese = generer_figures(
                    resultats       = resultats,
                    secteurs        = secteurs_figures,
                    iv_tous_par_sc  = iv_tous_par_sc,
                    output_dir      = dossier_figures,
                    nom_projet      = nom_projet,
                )
                for ch in (chemins_polaires or []):
                    if ch:
                        feedback.pushInfo(f"  Polaire  → {ch}")
                if chemin_synthese:
                    feedback.pushInfo(f"  Synthèse → {chemin_synthese}")
            except ImportError:
                feedback.pushWarning(
                    "matplotlib non disponible — figures non générées.\n"
                    "Installer via : pip install matplotlib --break-system-packages"
                )
            except Exception as e:
                feedback.pushWarning(f"Erreur génération figures : {e}")
        else:
            feedback.pushInfo(
                "Dossier figures non renseigné — figures non générées."
            )

        # -------------------------------------------------------------------
        # 12. Styles QGIS + couche anneaux
        # -------------------------------------------------------------------
        # -------------------------------------------------------------------
        # Export GPKG + chargement QGIS
        # -------------------------------------------------------------------
        feedback.pushInfo("\nExport des couches vectorielles...")
        save_opts = QgsVectorFileWriter.SaveVectorOptions()
        save_opts.driverName    = "GPKG"
        save_opts.fileEncoding  = "UTF-8"
        save_opts.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile

        def _sauver_et_charger(feats, champs, geom_type, chemin, nom_couche):
            """Écrit les features dans un GPKG et charge la couche dans QGIS."""
            lyr_mem = QgsVectorLayer(
                f"{'Polygon' if geom_type == QgsWkbTypes.Polygon else 'Point'}"
                f"?crs={scr_ref.authid()}", nom_couche, "memory"
            )
            prov = lyr_mem.dataProvider()
            prov.addAttributes(champs)
            lyr_mem.updateFields()
            prov.addFeatures(feats)
            lyr_mem.updateExtents()
            
            # FIX: Utilisation de *_ pour absorber dynamiquement toutes les valeurs supplémentaires
            # (QGIS 3.20+ retourne 4 valeurs au lieu de 3 ou 2)
            err, msg, *_ = QgsVectorFileWriter.writeAsVectorFormatV3(
                lyr_mem, chemin, QgsProject.instance().transformContext(), save_opts
            )
            
            if err != QgsVectorFileWriter.NoError:
                feedback.pushWarning(f"  Export {nom_couche} : {msg}")
                return None
            couche_gpkg = QgsVectorLayer(chemin, nom_couche, "ogr")
            if couche_gpkg.isValid():
                QgsProject.instance().addMapLayer(couche_gpkg)
                feedback.pushInfo(f"  {nom_couche} → {chemin}")
                return couche_gpkg
            return None

        from qgis.core import QgsProject
        couche_wedges = _sauver_et_charger(
            feats_wedge, champs_wedge, QgsWkbTypes.Polygon,
            chemin_wedges, f"{nom_projet} — Secteurs angulaires"
        )
        couche_pts = _sauver_et_charger(
            feats_pts, champs_pts, QgsWkbTypes.Point,
            chemin_pts, f"{nom_projet} — Éoliennes filtrées"
        )

        # Styles + anneaux
        try:
            from .styles import creer_couche_anneaux, appliquer_style_wedges
            creer_couche_anneaux(x_obs, y_obs, crs_authid=scr_ref.authid())
            if couche_wedges:
                appliquer_style_wedges(couche_wedges)
            feedback.pushInfo("  Couche anneaux + styles wedges appliqués.")
        except Exception as e:
            feedback.pushInfo(f"  Styles non appliqués : {e}")

        # Export CSV
        self._exporter_csv(resultats, chemin_csv, feedback)

        # Rapport texte
        with open(chemin_rapport, "w", encoding="utf-8") as f:
            f.write(rapport)
        feedback.pushInfo(f"  Rapport → {chemin_rapport}")

        feedback.pushInfo(f"\n{'='*60}")
        feedback.pushInfo(f"  Sorties dans : {output_dir}")
        feedback.pushInfo(f"  1_Vecteurs/  → wedges + éoliennes GPKG")
        feedback.pushInfo(f"  2_Figures/   → {4 + 1} PNG (4 polaires + synthèse)")
        feedback.pushInfo(f"  CSV + rapport à la racine")
        feedback.pushInfo(f"{'='*60}")

        feedback.setProgress(100)
        return {
            self.OUTPUT_RAPPORT: rapport, 
            self.OUTPUT_DIR:     output_dir
        }

    # -----------------------------------------------------------------------
    # Méthodes privées — wedges
    # -----------------------------------------------------------------------

    def _ecrire_wedges(
        self, sink, intervalles, sc_id, sc_nom, couronne,
        x_obs, y_obs, r_int, r_ext, statuts_str, type_arc,
        champs_wedge_ref=None,
    ):
        for (az_min, az_max) in intervalles:
            if az_max > 360.0:
                self._ecrire_wedge_unique(
                    sink, az_min, 360.0, sc_id, sc_nom, couronne,
                    x_obs, y_obs, r_int, r_ext, statuts_str, type_arc,
                    champs_wedge_ref,
                )
                self._ecrire_wedge_unique(
                    sink, 0.0, az_max - 360.0, sc_id, sc_nom, couronne,
                    x_obs, y_obs, r_int, r_ext, statuts_str, type_arc,
                    champs_wedge_ref,
                )
            else:
                self._ecrire_wedge_unique(
                    sink, az_min, az_max, sc_id, sc_nom, couronne,
                    x_obs, y_obs, r_int, r_ext, statuts_str, type_arc,
                    champs_wedge_ref,
                )

    def _ecrire_wedge_unique(
        self, sink, az_min, az_max, sc_id, sc_nom, couronne,
        x_obs, y_obs, r_int, r_ext, statuts_str, type_arc,
        champs_wedge_ref=None,
    ):
        amplitude = az_max - az_min
        if amplitude <= 0:
            return
        geom = generer_wedge_qgs(x_obs, y_obs, r_int, r_ext, az_min, az_max)
        if geom is None or geom.isEmpty():
            return
        feat = QgsFeature(champs_wedge_ref)
        feat.setGeometry(geom)
        feat.setAttributes([
            sc_id, sc_nom, couronne, type_arc, statuts_str,
            round(az_min, 4), round(az_max, 4), round(amplitude, 4),
        ])
        sink.append(feat)

    def _trouver_arc_vide_dominant(self, intervalles_fusionnes, ier_valeur):
        if not intervalles_fusionnes or ier_valeur <= 0:
            return None
        fus = sorted(intervalles_fusionnes, key=lambda x: x[0])
        meilleur = None
        meilleure_amp = -1.0
        for i in range(1, len(fus)):
            amp = fus[i][0] - fus[i - 1][1]
            if amp > meilleure_amp:
                meilleure_amp = amp
                meilleur = (fus[i - 1][1], fus[i][0])
        if fus:
            trou_circ = (360.0 - fus[-1][1]) + fus[0][0]
            if trou_circ > meilleure_amp:
                meilleur = (fus[-1][1], fus[0][0] + 360.0)
        return meilleur

    # -----------------------------------------------------------------------
    # Méthode privée — export CSV
    # -----------------------------------------------------------------------

    def _exporter_csv(self, resultats: dict, chemin: str, feedback) -> None:
        """
        Écrit le tableau de synthèse des 4 scénarios dans un fichier CSV
        compatible Excel Europe (encodage utf-8-sig, séparateur ";",
        virgule comme séparateur décimal pour les flottants).
        """
        def _fmt_float(val) -> str:
            """Formate un flottant avec 4 décimales et virgule décimale."""
            if val is None:
                return ""
            return f"{val:.4f}".replace(".", ",")

        def _fmt_angle(val) -> str:
            """Formate un angle avec 2 décimales et virgule décimale."""
            if val is None:
                return ""
            return f"{val:.2f}".replace(".", ",")

        def _fmt_int(val) -> str:
            if val is None:
                return ""
            return str(int(val))

        lignes = []
        for sc_id in [1, 2, 3, 4]:
            r = resultats.get(sc_id, {})
            if not r:
                continue
            ligne = [
                _fmt_int(sc_id),
                r.get("nom", ""),
                _fmt_angle(r.get("A")),
                _fmt_angle(r.get("Ap")),
                _fmt_angle(r.get("App")),
                _fmt_angle(r.get("IOH")),
                _fmt_angle(r.get("IOH_alt")),
                _fmt_angle(r.get("IOH_net")),
                _fmt_int(r.get("B")),
                _fmt_int(r.get("Bp")),
                _fmt_int(r.get("N")),
                _fmt_float(r.get("ID1")),
                _fmt_float(r.get("ID2_5km")),
                _fmt_float(r.get("ID2_10km")),
                _fmt_angle(r.get("IER")),
            ]
            lignes.append(ligne)

        try:
            # utf-8-sig = BOM UTF-8 → Excel Windows reconnaît les accents et °
            with open(chemin, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
                writer.writerow(CSV_ENTETE)
                writer.writerows(lignes)
            feedback.pushInfo(f"CSV exporté : {chemin}")
        except Exception as e:
            feedback.pushWarning(f"Échec de l'export CSV : {e}")

    # -----------------------------------------------------------------------
    # Méthode privée — rapport textuel
    # -----------------------------------------------------------------------

    def _generer_rapport(self, resultats: dict) -> str:
        sep       = "=" * 72
        ligne_sep = "-" * 72

        def v(sc_id, cle, fmt="{:.1f}"):
            r = resultats.get(sc_id, {})
            val = r.get(cle)
            if val is None:
                return "   N/A"
            try:
                return fmt.format(val)
            except Exception:
                return str(val)

        def al(sc_id, cle):
            return "⚠" if resultats.get(sc_id, {}).get(cle, False) else " "

        def ligne(label, cle, fmt="{:.1f}", cle_al=None):
            vals = []
            for sc in [1, 2, 3, 4]:
                txt = v(sc, cle, fmt)
                if cle_al:
                    txt = f"{txt}{al(sc, cle_al)}"
                vals.append(txt)
            return (
                f"  {label:<34} "
                f"{vals[0]:>10} {vals[1]:>10} {vals[2]:>10} {vals[3]:>10}"
            )

        lignes = [
            "",
            sep,
            "  SATURATION VISUELLE ÉOLIENNE — MÉTHODE DREAL HdF (fév. 2024) v3",
            sep,
            "",
            "  Seuils d'alerte :",
            f"    IOH > {SEUIL_IOH_DEG:.0f}°  |  ID1 > {SEUIL_ID1} éol/°  "
            f"|  ID2 > {SEUIL_ID2_KM2} éol/km²  |  IER < {SEUIL_IER_DEG:.0f}°",
            "  ⚠ = seuil dépassé  |  (espace) = sous le seuil",
            "",
            f"  {'Indice':<34} {'Sc.1':>10} {'Sc.2':>10} {'Sc.3':>10} {'Sc.4':>10}",
            ligne_sep,
            "  ANGLES OCCUPÉS",
            ligne("A — occ. 0–5 km (°)",             "A"),
            ligne("A' — occ. 5–10 km (°)",            "Ap"),
            ligne("A'' — doubles comptes (°)",         "App"),
            ligne_sep,
            "  INDICES D'OCCUPATION DE L'HORIZON (IOH)",
            ligne("IOH brut = A+A' (°)",               "IOH",      "{:.1f}", "alerte_IOH"),
            ligne("IOH alt. = A+0.5·A' (°)",           "IOH_alt"),
            ligne("IOH net  = A+A'−A'' (°)",           "IOH_net"),
            ligne_sep,
            "  COMPTAGES",
            ligne("B  — éol. 0–5 km",                 "B",        "{:d}"),
            ligne("B' — éol. 5–10 km",                "Bp",       "{:d}"),
            ligne("N  — éol. 0–10 km",                "N",        "{:d}"),
            ligne_sep,
            "  INDICES DE DENSITÉ",
            ligne("ID1 = B/(A+A') (éol/°)",           "ID1",      "{:.4f}", "alerte_ID1"),
            ligne("ID2 à  5 km = B/78   (éol/km²)",   "ID2_5km",  "{:.4f}"),
            ligne("ID2 à 10 km = N/314  (éol/km²)",   "ID2_10km", "{:.4f}", "alerte_ID2"),
            ligne_sep,
            "  ESPACE DE RESPIRATION",
            ligne("IER — arc vide max. (°)",           "IER",      "{:.1f}", "alerte_IER"),
            ligne_sep,
            "",
            "  Rappel des formules DREAL :",
            "  • IOH = A + A'  (alt. : A + 0,5·A' si justifié — PDF p.3)",
            "  • ID1 = B / (A + A')   [B = nb éol. 0–5 km]",
            "  • ID2 = B/78 (5 km)  ou  N/314 (10 km)  [éoliennes/km²]",
            "  • A'' = intersection angulaire 0–5 km ∩ 5–10 km",
            "  • IER = plus grand arc continu sans éolienne (0–10 km)",
            "",
            "  Scénarios :",
            "  Sc.1 — En service + Autorisé",
            "  Sc.2 — Sc.1 + Projet propre",
            "  Sc.3 — Sc.1 + En instruction",
            "  Sc.4 — Sc.3 + Projet propre",
            "",
            sep,
        ]
        return "\n".join(lignes)


# ===========================================================================
# Fonctions utilitaires module-level
# ===========================================================================

def _normaliser_statut(statut_brut: str) -> str:
    """
    Normalise la valeur brute du champ statut vers les catégories DREAL.
    Gère les variantes de casse, d'accentuation et les alias métier courants.
    """
    mapping = {
        "autorise":               "Autorisé",
        "autorisé":               "Autorisé",
        "en service":             "En service",
        "construit":              "En service",
        "built":                  "En service",
        "en instruction":         "En instruction",
        "instruction":            "En instruction",
        "en cours d'instruction": "En instruction",
    }
    return mapping.get(statut_brut.lower().strip(), statut_brut)


def _resoudre_diametre(
        feat,
        champ_diam: str | None,
        diam_global: float | None,
) -> float | None:
    """
    Résout le diamètre du rotor pour une entité donnée selon la hiérarchie :
      1. Valeur du champ attributaire (si spécifié, non NULL, > 0)
      2. Valeur globale (si > 0)
      3. None (le moteur math_utils appliquera son propre fallback)

    :param feat       : QgsFeature courante.
    :param champ_diam : Nom du champ diamètre (None si non fourni).
    :param diam_global: Diamètre global saisi dans le formulaire (None si non fourni).
    :return: Diamètre en mètres (float) ou None.
    """
    # Priorité 1 : champ attributaire
    if champ_diam:
        try:
            idx = feat.fields().indexOf(champ_diam)
            if idx >= 0:
                val = feat[champ_diam]
                if val is not None:
                    val_f = float(val)
                    if val_f > 0:
                        return val_f
        except (TypeError, ValueError):
            pass

    # Priorité 2 : valeur globale
    if diam_global and diam_global > 0:
        return diam_global

    # Priorité 3 : None → fallback dans math_utils
    return None


def _construire_intervalles_avec_secteurs(
        pool: list,
        x_obs: float,
        y_obs: float,
        rayon_min: float,
        rayon_max: float,
        couronne_label: str,
) -> tuple:
    """
    Variante de _construire_intervalles_rotor qui retourne en plus
    la liste des secteurs par parc pour les graphiques polaires.

    Même logique exacte que _construire_intervalles_rotor —
    un seul appel cone_parc_avec_rotor par parc, pas par mât.

    :returns: (intervalles_fusionnes, secteurs)
              secteurs = [{"tmin","tmax","couronne","statut","parc","is_projet"}, ...]
    """
    eol_couronne = [
        e for e in pool
        if rayon_min <= e["dist"] < rayon_max
    ]

    parcs: dict = {}
    for e in eol_couronne:
        parcs.setdefault(e["parc"], []).append(e)

    tous_intervalles = []
    secteurs          = []

    for nom_parc, eols in parcs.items():
        eol_coords = [(x_obs, y_obs, e["x"], e["y"]) for e in eols]
        diam_parc  = next(
            (e["diametre_m"] for e in eols if e["diametre_m"] and e["diametre_m"] > 0),
            None,
        )
        statut_parc  = eols[0]["statut"]
        is_projet    = eols[0]["source"] == "projet"

        try:
            tmin, tmax = cone_parc_avec_rotor(eol_coords, diam_parc)
        except ValueError:
            continue

        segments = normaliser_intervalle(tmin, tmax)
        tous_intervalles.extend(segments)

        for seg in segments:
            secteurs.append({
                "tmin":      seg[0],
                "tmax":      seg[1],
                "couronne":  couronne_label,
                "statut":    statut_parc,
                "parc":      nom_parc,
                "is_projet": is_projet,
            })

    return fusionner_intervalles(tous_intervalles), secteurs


def _construire_intervalles_rotor(
        pool: list,
        x_obs: float,
        y_obs: float,
        rayon_min: float,
        rayon_max: float,
) -> list:
    """
    Construit et fusionne les intervalles angulaires pour une couronne,
    en utilisant cone_parc_avec_rotor() qui applique la logique
    trigonométrique conditionnelle.

    Pour chaque parc, on passe la liste complète des tuples
    (x_obs, y_obs, x_eol, y_eol) et le diamètre résolu par entité.

    Stratégie de diamètre au niveau parc :
      - On prend le diamètre de la PREMIÈRE éolienne valide du parc.
      - Si aucune n'a de diamètre, on passe None (fallback math_utils).
    Cette simplification est cohérente car dans un parc réel, toutes
    les machines ont le même modèle (donc le même rotor).

    :param pool      : Liste de dicts éolienne {'x','y','az','dist','parc','diametre_m',...}.
    :param x_obs     : Coordonnée X du lieu de vie.
    :param y_obs     : Coordonnée Y du lieu de vie.
    :param rayon_min : Borne inférieure de la couronne (m).
    :param rayon_max : Borne supérieure de la couronne (m).
    :return: Liste d'intervalles fusionnés (theta_min, theta_max) en degrés.
    """
    # Filtrage par couronne
    eol_couronne = [
        e for e in pool
        if rayon_min <= e["dist"] < rayon_max
    ]

    # Regroupement par parc
    parcs: dict = {}
    for e in eol_couronne:
        parcs.setdefault(e["parc"], []).append(e)

    tous_intervalles = []

    for nom_parc, eols in parcs.items():
        # Tuples (x_obs, y_obs, x_eol, y_eol) pour cone_parc_avec_rotor
        eol_coords = [
            (x_obs, y_obs, e["x"], e["y"])
            for e in eols
        ]

        # Diamètre du parc : première valeur valide trouvée
        diam_parc = next(
            (e["diametre_m"] for e in eols if e["diametre_m"] and e["diametre_m"] > 0),
            None,
        )

        try:
            tmin, tmax = cone_parc_avec_rotor(eol_coords, diam_parc)
        except ValueError:
            continue

        segments = normaliser_intervalle(tmin, tmax)
        tous_intervalles.extend(segments)

    return fusionner_intervalles(tous_intervalles)