# -*- coding: utf-8 -*-
"""
Tests unitaires pour math_utils.py.

Ce module ne dépend d'aucune API QGIS (qgis.core, qgis.PyQt), il est
donc testable avec un simple `pytest`, sans environnement QGIS complet.

Lancer avec :
    pytest tests/
"""

import math
import sys
import os

# Permet d'importer saturation_dreal.math_utils sans installer le paquet
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from saturation_dreal.math_utils import (
    calcul_azimut,
    distance_plane,
    normaliser_intervalle,
    fusionner_intervalles,
    somme_angles,
    intersection_intervalles,
    calculer_ier,
)


# ---------------------------------------------------------------------------
# Azimut / distance
# ---------------------------------------------------------------------------

def test_calcul_azimut_nord():
    # Éolienne plein Nord (dx=0, dy>0) → azimut 0°
    assert calcul_azimut(0, 0, 0, 100) == 0.0


def test_calcul_azimut_est():
    # Éolienne plein Est (dx>0, dy=0) → azimut 90°
    assert calcul_azimut(0, 0, 100, 0) == 90.0


def test_calcul_azimut_toujours_positif():
    # Toute éolienne au Sud-Ouest doit rester dans [0°, 360°[
    az = calcul_azimut(0, 0, -100, -100)
    assert 0.0 <= az < 360.0


def test_distance_plane_pythagore():
    assert distance_plane(0, 0, 3000, 4000) == 5000.0


# ---------------------------------------------------------------------------
# Normalisation d'intervalles
# ---------------------------------------------------------------------------

def test_normaliser_intervalle_simple():
    assert normaliser_intervalle(10, 80) == [(10.0, 80.0)]


def test_normaliser_intervalle_franchissement_nord():
    # (350°, 370°) doit être coupé en deux sous-intervalles
    result = normaliser_intervalle(350, 370)
    assert result == [(350.0, 360.0), (0.0, 10.0)]


# ---------------------------------------------------------------------------
# Fusion d'intervalles
# ---------------------------------------------------------------------------

def test_fusionner_intervalles_disjoints():
    intervalles = [(0, 10), (50, 60)]
    assert fusionner_intervalles(intervalles) == [(0, 10), (50, 60)]


def test_fusionner_intervalles_chevauchants():
    intervalles = [(0, 10), (8, 20)]
    fusion = fusionner_intervalles(intervalles)
    assert fusion == [(0, 20)]


def test_somme_angles():
    intervalles = [(0, 10), (20, 45)]
    assert somme_angles(intervalles) == 35.0


# ---------------------------------------------------------------------------
# Intersection (double comptage entre couronnes)
# ---------------------------------------------------------------------------

def test_intersection_intervalles_partielle():
    set_a = [(0, 50)]
    set_b = [(30, 80)]
    result = intersection_intervalles(set_a, set_b)
    assert result == [(30, 50)]


def test_intersection_intervalles_vide():
    set_a = [(0, 10)]
    set_b = [(20, 30)]
    assert intersection_intervalles(set_a, set_b) == []


# ---------------------------------------------------------------------------
# Indice d'Espace de Respiration (IER)
# ---------------------------------------------------------------------------

def test_calculer_ier_aucune_occupation():
    assert calculer_ier([]) == 360.0


def test_calculer_ier_horizon_totalement_occupe():
    assert calculer_ier([(0, 360)]) == 0.0


def test_calculer_ier_deux_secteurs():
    # Deux secteurs opposés de 30° chacun → le plus grand vide doit être
    # supérieur à 0 et inférieur à 360°
    intervalles = [(0, 30), (180, 210)]
    ier = calculer_ier(intervalles)
    assert 0.0 < ier < 360.0
