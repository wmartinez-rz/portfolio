# -*- coding: utf-8 -*-
"""
math_utils.py — Cerveau mathématique du plugin Saturation Visuelle DREAL HdF.
Version 3 — Calcul trigonométrique conditionnel du cône visuel par rotor.

Logique du cône visuel (fonction cone_parc_avec_rotor) :

  CAS A — Diamètre défini par l'utilisateur (valeur > 0) :
    → Calcul trigonométrique analytique pour TOUTES les éoliennes.
    → Le rotor est modélisé perpendiculairement à la ligne de visée
      (scénario du pire cas géométrique).
    → Pour les parcs multi-mâts, la translation s'applique aux deux
      machines extrêmes pour élargir dynamiquement l'enveloppe du parc.

  CAS B — Aucun diamètre fourni (None ou 0) :
    → Parc multi-mâts  : enveloppe centro-à-centro (comportement historique).
    → Éolienne isolée  : diamètre institutionnel par défaut = 120 m (R=60 m),
      puis calcul trigonométrique identique au CAS A.

Convention angulaire : azimuts en degrés [0°, 360°[, sens horaire depuis le Nord.
Coordonnées : système projeté plan en mètres (SCR de la couche lieu de vie).
"""

import math
from typing import List, Tuple, Optional

# ---------------------------------------------------------------------------
# Constantes DREAL
# ---------------------------------------------------------------------------

# Tolérance de fusion des intervalles (en degrés) — évite le "bruit" visuel
TOLERANCE_FUSION_DEG = 0.5

# Diamètre de rotor institutionnel par défaut (éolienne isolée, sans mesure fournie)
# Conforme à la convention DREAL : représente une machine standard moderne.
DIAMETRE_ROTOR_DEFAUT_M = 120.0   # → R = 60.0 m

# Rayons des deux couronnes d'analyse (en mètres)
RAYON_INTERNE_M = 5_000.0    # couronne 0 – 5 km
RAYON_EXTERNE_M = 10_000.0   # couronne 5 – 10 km


# ---------------------------------------------------------------------------
# 1. Azimut et distance
# ---------------------------------------------------------------------------

def calcul_azimut(x_obs: float, y_obs: float,
                  x_eol: float, y_eol: float) -> float:
    """
    Calcule l'azimut géographique (degrés, sens horaire depuis le Nord)
    depuis le lieu de vie vers une éolienne, en coordonnées planes projetées.

    Résultat garanti dans [0°, 360°[.
    """
    dx = x_eol - x_obs
    dy = y_eol - y_obs
    return math.degrees(math.atan2(dx, dy)) % 360.0


def distance_plane(x_obs: float, y_obs: float,
                   x_eol: float, y_eol: float) -> float:
    """
    Distance euclidienne (mètres) entre le lieu de vie et une éolienne.
    """
    return math.hypot(x_eol - x_obs, y_eol - y_obs)


# ---------------------------------------------------------------------------
# 2. Calcul de l'emprise angulaire d'une éolienne par translation du rotor
# ---------------------------------------------------------------------------

def _azimuts_rotor(x_obs: float, y_obs: float,
                   x_eol: float, y_eol: float,
                   rayon_rotor_m: float) -> Tuple[float, float]:
    """
    Calcule les azimuts des deux extrémités physiques du rotor depuis l'observateur,
    en modélisant le rotor perpendiculairement à la ligne de visée (pire cas).

    Soit P_obs le lieu de vie et P_eol le centre de l'éolienne.
    Le vecteur de visée normalisé est (dx/D, dy/D).
    Le vecteur perpendiculaire est (-dy/D, dx/D).
    Les deux extrémités du rotor sont :
      P1 (gauche)  : x_eol - R*(dy/D),  y_eol + R*(dx/D)
      P2 (droite)  : x_eol + R*(dy/D),  y_eol - R*(dx/D)

    :param x_obs, y_obs : Coordonnées du lieu de vie.
    :param x_eol, y_eol : Coordonnées du centre de l'éolienne.
    :param rayon_rotor_m: Rayon du rotor R = Diamètre / 2 (mètres).
    :return: Tuple (az_gauche, az_droite) en degrés [0, 360[.
             az_gauche < az_droite sauf franchissement du Nord.
    """
    dx = x_eol - x_obs
    dy = y_eol - y_obs
    D = math.hypot(dx, dy)

    if D < 1e-6:
        # Éolienne confondue avec l'observateur : cas dégénéré, azimut nul
        return 0.0, 0.0

    # Extrémité gauche P1
    x1 = x_eol - rayon_rotor_m * (dy / D)
    y1 = y_eol + rayon_rotor_m * (dx / D)
    # Extrémité droite P2
    x2 = x_eol + rayon_rotor_m * (dy / D)
    y2 = y_eol - rayon_rotor_m * (dx / D)

    # Azimuts depuis l'observateur vers P1 et P2
    az1 = math.degrees(math.atan2(x1 - x_obs, y1 - y_obs)) % 360.0
    az2 = math.degrees(math.atan2(x2 - x_obs, y2 - y_obs)) % 360.0

    return az1, az2


def _ordonner_azimuts_rotor(az1: float, az2: float) -> Tuple[float, float]:
    """
    Ordonne deux azimuts de rotor en (theta_min, theta_max) en choisissant
    le sens qui donne la plus petite amplitude (le rotor occupe < 180°).

    Gère le franchissement du Nord : si l'écart direct > 180°, l'intervalle
    "réel" traverse le Nord.

    :return: (theta_min, theta_max) — theta_max peut dépasser 360°
             si l'intervalle franchit le Nord.
    """
    diff = (az2 - az1) % 360.0
    if diff <= 180.0:
        # Sens direct az1 → az2
        return az1, az1 + diff
    else:
        # Sens indirect : l'arc court va de az2 à az1 en passant par le Nord
        # On représente ça comme az2 → az1+360°
        return az2, az2 + (360.0 - diff)


# ---------------------------------------------------------------------------
# 3. Cône visuel d'un parc (nouvelle version conditionnelle)
# ---------------------------------------------------------------------------

def cone_parc_avec_rotor(
        eol_coords: List[Tuple[float, float, float, float]],
        diametre_rotor_m: Optional[float],
) -> Tuple[float, float]:
    """
    Calcule l'intervalle angulaire [theta_min, theta_max] occupé par un parc
    depuis le lieu de vie, avec gestion conditionnelle du rotor.

    Signature :
      eol_coords : liste de tuples (x_obs, y_obs, x_eol, y_eol) pour chaque
                   éolienne du parc (toutes les machines ont le même observateur).
      diametre_rotor_m : diamètre du rotor en mètres fourni par l'utilisateur
                         (None ou 0 = non fourni).

    Logique appliquée :
    ┌─────────────────────────────────────────────────────────────────────┐
    │ CAS A — diametre_rotor_m est valide (> 0)                          │
    │   → calcul trigonométrique pour TOUTES les éoliennes               │
    │   → pour multi-mâts : on prend les deux machines angulairement     │
    │     extrêmes, on translate leur rotor, et on prend l'enveloppe     │
    ├─────────────────────────────────────────────────────────────────────┤
    │ CAS B — diametre_rotor_m est None ou 0                             │
    │   → 1 seule éolienne : diamètre par défaut 120 m → calcul trigo   │
    │   → multi-mâts : enveloppe centro-à-centro (historique)           │
    └─────────────────────────────────────────────────────────────────────┘

    :return: (theta_min, theta_max) en degrés — peut dépasser 360°.
    :raises ValueError: Si eol_coords est vide.
    """
    if not eol_coords:
        raise ValueError("cone_parc_avec_rotor : liste d'éoliennes vide.")

    nb = len(eol_coords)
    x_obs, y_obs = eol_coords[0][0], eol_coords[0][1]

    # -----------------------------------------------------------------------
    # CAS A : diamètre fourni → calcul trigonométrique pour tout le parc
    # -----------------------------------------------------------------------
    if diametre_rotor_m and diametre_rotor_m > 0:
        R = diametre_rotor_m / 2.0
        return _enveloppe_trigonometrique(eol_coords, R)

    # -----------------------------------------------------------------------
    # CAS B : aucun diamètre fourni
    # -----------------------------------------------------------------------

    # --- B1 : éolienne isolée → diamètre institutionnel par défaut ---
    if nb == 1:
        R_defaut = DIAMETRE_ROTOR_DEFAUT_M / 2.0
        return _enveloppe_trigonometrique(eol_coords, R_defaut)

    # --- B2 : multi-mâts → enveloppe centro-à-centro (comportement historique) ---
    return _enveloppe_centro_a_centro(eol_coords)


def _enveloppe_trigonometrique(
        eol_coords: List[Tuple[float, float, float, float]],
        R: float,
) -> Tuple[float, float]:
    """
    Calcule l'enveloppe angulaire d'un ensemble d'éoliennes en appliquant
    la translation du rotor (rayon R) à chaque machine.

    Pour les parcs multi-mâts, on identifie d'abord les deux machines
    angulairement extrêmes (gauche et droite), puis on translate leur rotor
    pour obtenir les bornes réelles [theta_min, theta_max] du parc.

    :param eol_coords: Liste de (x_obs, y_obs, x_eol, y_eol).
    :param R: Rayon du rotor (mètres).
    :return: (theta_min, theta_max) — peut dépasser 360°.
    """
    x_obs, y_obs = eol_coords[0][0], eol_coords[0][1]

    # Calcul des azimuts centraux pour identifier les extrêmes
    azimuts_centraux = [
        calcul_azimut(x_obs, y_obs, x_eol, y_eol)
        for (_, _, x_eol, y_eol) in eol_coords
    ]

    if len(eol_coords) == 1:
        # Une seule éolienne : translation directe
        _, _, x_eol, y_eol = eol_coords[0]
        az1, az2 = _azimuts_rotor(x_obs, y_obs, x_eol, y_eol, R)
        return _ordonner_azimuts_rotor(az1, az2)

    # Multi-mâts : identifier les deux éoliennes angulairement extrêmes
    # après correction du franchissement du Nord
    az_tries_idx = _trier_azimuts_avec_franchissement(azimuts_centraux)

    # Indice de la machine la plus à gauche (theta_min) et la plus à droite (theta_max)
    idx_gauche = az_tries_idx[0]
    idx_droite = az_tries_idx[-1]

    _, _, x_g, y_g = eol_coords[idx_gauche]
    _, _, x_d, y_d = eol_coords[idx_droite]

    # Translation du rotor sur la machine gauche → on prend son extrémité gauche
    az1_g, az2_g = _azimuts_rotor(x_obs, y_obs, x_g, y_g, R)
    tmin_g, tmax_g = _ordonner_azimuts_rotor(az1_g, az2_g)
    theta_min = tmin_g  # extrémité gauche de la machine gauche

    # Translation du rotor sur la machine droite → on prend son extrémité droite
    az1_d, az2_d = _azimuts_rotor(x_obs, y_obs, x_d, y_d, R)
    tmin_d, tmax_d = _ordonner_azimuts_rotor(az1_d, az2_d)
    theta_max_candidate = tmax_d  # extrémité droite de la machine droite

    # S'assurer que theta_max > theta_min (gestion du franchissement)
    if theta_max_candidate <= theta_min:
        theta_max_candidate += 360.0

    return theta_min, theta_max_candidate


def _enveloppe_centro_a_centro(
        eol_coords: List[Tuple[float, float, float, float]],
) -> Tuple[float, float]:
    """
    Enveloppe angulaire classique (historique) : de centre à centre,
    sans ajout de dimension de rotor.
    Utilisée pour les parcs multi-mâts quand aucun diamètre n'est fourni.

    :param eol_coords: Liste de (x_obs, y_obs, x_eol, y_eol).
    :return: (theta_min, theta_max) — peut dépasser 360°.
    """
    x_obs, y_obs = eol_coords[0][0], eol_coords[0][1]
    azimuts = [
        calcul_azimut(x_obs, y_obs, x_eol, y_eol)
        for (_, _, x_eol, y_eol) in eol_coords
    ]

    az_tries_idx = _trier_azimuts_avec_franchissement(azimuts)
    az_corriges = _corriger_franchissement_nord(
        [azimuts[i] for i in az_tries_idx]
    )
    return az_corriges[0], az_corriges[-1]


def _trier_azimuts_avec_franchissement(azimuts: List[float]) -> List[int]:
    """
    Trie les indices des azimuts en détectant et corrigeant le
    franchissement du Nord (amplitude directe > 180°).

    Retourne les indices dans l'ordre angulaire corrigé.
    """
    indexed = sorted(enumerate(azimuts), key=lambda x: x[1])
    az_tries = [az for _, az in indexed]
    amplitude = az_tries[-1] - az_tries[0]

    if amplitude > 180.0:
        # Franchissement du Nord : décaler les valeurs < 180° de +360°
        corriges = [
            (i, az + 360.0 if az < 180.0 else az)
            for i, az in enumerate(azimuts)
        ]
        corriges.sort(key=lambda x: x[1])
        return [i for i, _ in corriges]
    else:
        return [i for i, _ in indexed]


def _corriger_franchissement_nord(azimuts_tries: List[float]) -> List[float]:
    """
    Applique la correction +360° aux azimuts < 180° dans une liste triée
    qui franchit le Nord. Retourne la liste corrigée.
    """
    amplitude = azimuts_tries[-1] - azimuts_tries[0]
    if amplitude > 180.0:
        return [az + 360.0 if az < 180.0 else az for az in azimuts_tries]
    return azimuts_tries


# ---------------------------------------------------------------------------
# 4. Compatibilité ascendante — ancienne signature cone_parc()
# ---------------------------------------------------------------------------

def cone_parc(azimuts: List[float],
              rayon_rotor_m: Optional[float] = None,
              distance_m: Optional[float] = None) -> Tuple[float, float]:
    """
    [Conservé pour compatibilité] Calcule l'intervalle [theta_min, theta_max]
    d'un parc depuis une liste d'azimuts seuls (sans coordonnées).

    Utilisé dans les contextes où les coordonnées individuelles ne sont
    pas disponibles. Préférer cone_parc_avec_rotor() pour les nouveaux appels.

    Comportement :
    - 1 azimut + rayon_rotor_m fourni  → calcul trigonométrique simple (atan)
    - 1 azimut sans rayon              → diamètre par défaut 120 m via atan
                                         (distance_m requise pour être précis ;
                                          sinon, fallback sur 1° de demi-angle)
    - Multi-azimuts                    → enveloppe avec correction Nord
    """
    if not azimuts:
        raise ValueError("cone_parc : liste d'azimuts vide.")

    if len(azimuts) == 1:
        az = azimuts[0]
        if rayon_rotor_m and rayon_rotor_m > 0 and distance_m and distance_m > 0:
            demi_angle = math.degrees(math.atan(rayon_rotor_m / distance_m))
        elif distance_m and distance_m > 0:
            # Diamètre par défaut
            R_defaut = DIAMETRE_ROTOR_DEFAUT_M / 2.0
            demi_angle = math.degrees(math.atan(R_defaut / distance_m))
        else:
            # Aucune donnée de distance : demi-angle forfaitaire minimal
            demi_angle = 1.0
        return (az - demi_angle) % 360.0, (az + demi_angle) % 360.0

    # Multi-mâts : enveloppe centro-à-centro
    az_tries = sorted(azimuts)
    amplitude = az_tries[-1] - az_tries[0]
    if amplitude > 180.0:
        corriges = [az + 360.0 if az < 180.0 else az for az in az_tries]
        return min(corriges), max(corriges)
    return az_tries[0], az_tries[-1]


# ---------------------------------------------------------------------------
# 5. Normalisation d'un intervalle angulaire en segments [0°, 360°[
# ---------------------------------------------------------------------------

def normaliser_intervalle(theta_min: float,
                          theta_max: float) -> List[Tuple[float, float]]:
    """
    Normalise un intervalle angulaire (potentiellement > 360°) en une liste
    de sous-intervalles dans [0°, 360°[.

    Exemples :
      (350°, 370°) → [(350°, 360°), (0°, 10°)]
      (10°,  80°)  → [(10°, 80°)]
    """
    tmin = theta_min % 360.0
    tmax = tmin + (theta_max - theta_min)   # conservation de l'amplitude
    if tmax <= 360.0:
        return [(tmin, tmax)]
    return [(tmin, 360.0), (0.0, tmax - 360.0)]


# ---------------------------------------------------------------------------
# 6. Fusion d'intervalles (Line Sweep) avec tolérance et circularité
# ---------------------------------------------------------------------------

def fusionner_intervalles(
        intervalles: List[Tuple[float, float]],
        tolerance: float = TOLERANCE_FUSION_DEG,
) -> List[Tuple[float, float]]:
    """
    Fusionne une liste d'intervalles 1D en supprimant les chevauchements
    et les micro-écarts inférieurs à la tolérance DREAL (0.5°).

    Algorithme Line Sweep :
    1. Tri par borne inférieure.
    2. Extension de l'intervalle courant si chevauchement ou écart ≤ tolérance.
    3. Passe circulaire : fusion du dernier intervalle avec le premier
       si leur écart via le Nord est ≤ tolérance.
    """
    if not intervalles:
        return []

    tries = sorted(intervalles, key=lambda iv: iv[0])
    fusionnes = [tries[0]]

    for debut, fin in tries[1:]:
        d_cur, f_cur = fusionnes[-1]
        if debut <= f_cur + tolerance:
            fusionnes[-1] = (d_cur, max(f_cur, fin))
        else:
            fusionnes.append((debut, fin))

    # Fusion circulaire (franchissement du Nord entre dernier et premier)
    if len(fusionnes) > 1:
        d0, f0 = fusionnes[0]
        dl, fl = fusionnes[-1]
        if fl + tolerance >= 360.0 + d0:
            fusionnes = [(dl, f0 + 360.0)] + fusionnes[1:-1]

    return fusionnes


def somme_angles(intervalles: List[Tuple[float, float]]) -> float:
    """Somme des amplitudes de tous les intervalles (en degrés)."""
    return sum(f - d for d, f in intervalles)


# ---------------------------------------------------------------------------
# 7. Intersection entre deux ensembles d'intervalles (doubles comptes A'')
# ---------------------------------------------------------------------------

def intersection_intervalles(
        set_a: List[Tuple[float, float]],
        set_b: List[Tuple[float, float]],
) -> List[Tuple[float, float]]:
    """
    Intersection géométrique stricte entre deux ensembles d'intervalles.
    Calcule A'' = angles présents dans les deux couronnes simultanément.
    """
    intersections = []
    for (a_min, a_max) in set_a:
        for (b_min, b_max) in set_b:
            d = max(a_min, b_min)
            f = min(a_max, b_max)
            if f > d:
                intersections.append((d, f))
    return intersections


# ---------------------------------------------------------------------------
# 8. Indice d'Espace de Respiration (IER)
# ---------------------------------------------------------------------------

def calculer_ier(tous_intervalles: List[Tuple[float, float]]) -> float:
    """
    Plus grand arc vide continu sur 360°, tous parcs et couronnes confondus.

    Méthode :
    1. Fusionner tous les intervalles occupés.
    2. Calculer les trous entre intervalles successifs.
    3. Calculer le trou circulaire (entre fin du dernier et début du premier).
    4. Retourner le maximum.
    """
    if not tous_intervalles:
        return 360.0

    fus = fusionner_intervalles(tous_intervalles)
    if not fus:
        return 360.0

    if len(fus) == 1:
        return max(0.0, 360.0 - (fus[0][1] - fus[0][0]))

    vides = []
    for i in range(1, len(fus)):
        trou = fus[i][0] - fus[i - 1][1]
        if trou > 0:
            vides.append(trou)

    # Trou circulaire (via le Nord)
    trou_circ = (360.0 - fus[-1][1]) + fus[0][0]
    if trou_circ > 0:
        vides.append(trou_circ)

    return max(vides) if vides else 0.0


# ---------------------------------------------------------------------------
# 9. Génération de géométrie Wedge (portion de couronne annulaire)
# ---------------------------------------------------------------------------

def generer_wedge_qgs(
        x_centre: float,
        y_centre: float,
        rayon_interne_m: float,
        rayon_externe_m: float,
        theta_min_deg: float,
        theta_max_deg: float,
        nb_points: int = 64,
):
    """
    Génère la QgsGeometry d'un secteur de couronne annulaire (wedge).

    Tracé :
      Arc extérieur (sens horaire, theta_min → theta_max)
      → Arc intérieur (sens anti-horaire, theta_max → theta_min)
      → Fermeture au centre si rayon_interne = 0

    Convention : azimuts horaires depuis le Nord, coordonnées planes.
    """
    try:
        from qgis.core import QgsGeometry, QgsPointXY
    except ImportError:
        raise ImportError("generer_wedge_qgs doit être exécuté dans QGIS.")

    amplitude = theta_max_deg - theta_min_deg
    if amplitude <= 0 or amplitude > 360.0:
        return None

    points = []

    # Arc extérieur
    for i in range(nb_points + 1):
        az_rad = math.radians(theta_min_deg + amplitude * i / nb_points)
        points.append(QgsPointXY(
            x_centre + rayon_externe_m * math.sin(az_rad),
            y_centre + rayon_externe_m * math.cos(az_rad),
        ))

    # Arc intérieur ou fermeture au centre
    if rayon_interne_m > 0:
        for i in range(nb_points + 1):
            az_rad = math.radians(theta_max_deg - amplitude * i / nb_points)
            points.append(QgsPointXY(
                x_centre + rayon_interne_m * math.sin(az_rad),
                y_centre + rayon_interne_m * math.cos(az_rad),
            ))
    else:
        points.append(QgsPointXY(x_centre, y_centre))

    points.append(points[0])
    return QgsGeometry.fromPolygonXY([points])
