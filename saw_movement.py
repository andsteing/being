#!/usr/local/python3
"""Slow Sine movement on the motors."""
from being.awakening import awake
from being.blocks import Sawtooth, Trafo
from being.motors import RotaryMotor
from being.resources import manage_resources
from being.constants import TAU
from being.logging import setup_logging
import logging


# Params
MOTOR_IDS = [1]
FREQUENCY = 1.0

setup_logging(level=logging.WARNING)

with manage_resources():
    saw = Sawtooth(FREQUENCY)
    for nodeId in MOTOR_IDS:
        mot = RotaryMotor(nodeId, gearNumerator=69, gearDenumerator=13)
        saw | mot

    awake(saw)