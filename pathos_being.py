#!/usr/local/python3
"""Pathos being for linear motors."""
import logging

from being.awakening import awake
from being.backends import CanBackend
from being.behavior import Behavior
from being.logging import setup_logging, suppress_other_loggers
from being.motion_player import MotionPlayer
from being.motors import LinearMotor, RotaryMotor
from being.resources import register_resource, manage_resources
from being.sensors import SensorGpio


# Params
MOTOR_NAME: str = 'LM1247'
"""Motor name."""

#setup_logging()
suppress_other_loggers()
logging.basicConfig(level=10)


with manage_resources():
    # Scan for motors
    network = CanBackend.single_instance_setdefault()
    register_resource(network, duplicates=False)
    motors = [
        LinearMotor(nodeId, motor=MOTOR_NAME, name=f'Motor ID {nodeId}')
        for nodeId in network.scan_for_node_ids()
    ]
    if not motors:
        raise RuntimeError('Found no motors!')

    # Initialize remaining being blocks
    sensor = SensorGpio(channel=6)
    behavior = Behavior.from_config('behavior.json')
    motionPlayer = MotionPlayer(ndim=len(motors))

    # Make block connections
    sensor | behavior | motionPlayer
    for output, motor in zip(motionPlayer.positionOutputs, motors):
        output.connect(motor.input)

    awake(behavior)
