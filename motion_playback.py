from being.being import awake
from being.motion_player import MotionPlayer
from being.motor import Motor
from being.resources import manage_resources


ROD_LENGTH = 0.04


with manage_resources():
    motor = Motor(nodeId=8, length=ROD_LENGTH)
    mp = MotionPlayer()
    awake(mp | motor)
