"""Motor blocks."""
from typing import Optional

from being.backends import CanBackend
from being.block import Block
from being.can import load_object_dictionary
from being.can.cia_402 import CiA402Node, OperationMode, which_state
from being.can.cia_402 import State as CiA402State
from being.can.homing import HomingState, crude_linear_homing
from being.can.nmt import PRE_OPERATIONAL
from being.can.vendor import stringify_faulhaber_error
from being.config import CONFIG
from being.constants import FORWARD
from being.error import BeingError
from being.kinematics import State as KinematicState
from being.kinematics import kinematic_filter
from being.logging import get_logger
from being.math import sign
from being.resources import register_resource


class DriveError(BeingError):

    """Something went wrong on the drive."""


class Motor(Block):

    """Motor base class."""

    def __init__(self):
        super().__init__()
        self.homing = HomingState.UNHOMED
        self.homingJob = None
        self.add_value_input('targetPosition')
        self.add_value_output('actualPosition')

    def home(self):
        pass


class LinearMotor(Motor):

    """Motor blocks which takes set-point values through its inputs and outputs
    the current actual position value through its output. The input position
    values are filtered with a kinematic filter. Encapsulates a and setups a
    CiA402Node. Currently only tested with Faulhaber linear drive (0.04 m).

    Attributes:
        network (CanBackend): Associsated network:
        node (CiA402Node): Drive node.
    """

    def __init__(self,
             nodeId: int,
             length: Optional[float] = None,
             direction: float = FORWARD,
             homingDirection: Optional[float] = None,
             maxSpeed: float = 1.,
             maxAcc: float = 1.,
             network: Optional[CanBackend] = None,
             node: Optional[CiA402Node] = None,
             objectDictionary = None,
        ):
        """Args:
            nodeId: CANopen node id.

        Kwargs:
            length: Rod length if known.
            direction: Movement orientation.
            homingDirection: Initial homing direction. Default same as `direction`.
            maxSpeed: Maximum speed.
            maxAcc: Maximum acceleration.
            network: External network (dependency injection).
            node: Drive node (dependency injection).
            objectDictionary: Object dictionary for CiA402Node. If will be tried
                to identified from known EDS files.
        """
        super().__init__()
        if homingDirection is None:
            homingDirection = direction

        if network is None:
            network = CanBackend.single_instance_setdefault()
            register_resource(network, duplicates=False)

        if node is None:
            if objectDictionary is None:
                objectDictionary = load_object_dictionary(network, nodeId)

            node = CiA402Node(nodeId, objectDictionary, network)

        self.length = length
        self.direction = sign(direction)
        self.homingDirection = sign(homingDirection)
        self.network = network
        self.node = node
        self.maxSpeed = maxSpeed
        self.maxAcc = maxAcc
        self.logger = get_logger(str(self))

        self.configure_node()

        self.node.nmt.state = PRE_OPERATIONAL
        self.node.set_state(CiA402State.READY_TO_SWITCH_ON)
        self.node.set_operation_mode(OperationMode.CYCLIC_SYNCHRONOUS_POSITION)

    @property
    def nodeId(self) -> int:
        """CAN node id."""
        return self.node.id

    def configure_node(self):
        """Configure Faulhaber node (some settings via SDO).

        Kwargs:
        """
        units = self.node.units

        generalSettings = self.node.sdo['General Settings']
        generalSettings['Pure Sinus Commutation'].raw = 1
        #generalSettings['Activate Position Limits in Velocity Mode'].raw = 1
        #generalSettings['Activate Position Limits in Position Mode'].raw = 1

        filterSettings = self.node.sdo['Filter Settings']
        filterSettings['Sampling Rate'].raw = 4
        filterSettings['Gain Scheduling Velocity Controller'].raw = 1

        velocityController = self.node.sdo['Velocity Control Parameter Set']
        #velocityController['Proportional Term POR'].raw = 44
        #velocityController['Integral Term I'].raw = 50

        posController = self.node.sdo['Position Control Parameter Set']
        #posController['Proportional Term PP'].raw = 15
        #posController['Derivative Term PD'].raw = 10
        # Some softer params from pygmies
        #posController['Proportional Term PP'].raw = 8
        #posController['Derivative Term PD'].raw = 14

        curController = self.node.sdo['Current Control Parameter Set']
        curController['Continuous Current Limit'].raw = 0.550 * units.current  # [mA]
        curController['Peak Current Limit'].raw = 1.640 * units.current  # [mA]
        curController['Integral Term CI'].raw = 3

        self.node.sdo['Max Profile Velocity'].raw = self.maxSpeed * units.kinematics  # [mm / s]
        self.node.sdo['Profile Acceleration'].raw = self.maxAcc * units.kinematics  # [mm / s^2]
        self.node.sdo['Profile Deceleration'].raw = self.maxAcc * units.kinematics  # [mm / s^2]

    def home(self):
        """Home motor."""
        self.homingJob = crude_linear_homing(self, direction=self.homingDirection)
        self.homing = HomingState.ONGOING

    def update(self):
        err = self.node.pdo['Error Register'].raw
        if err:
            msg = stringify_faulhaber_error(err)
            #raise DriveError(msg)
            self.logger.error('DriveError: %s', msg)

        if self.homing is HomingState.HOMED:
            sw = self.node.pdo['Statusword'].raw  # This takes approx. 0.027 ms
            if which_state(sw) is CiA402State.OPERATION_ENABLE:
                if self.direction > 0:
                    tarPos = self.targetPosition.value
                else:
                    tarPos = self.length - self.targetPosition.value

                self.node.set_target_position(tarPos)

        elif self.homing is HomingState.ONGOING:
            self.homing = next(self.homingJob)

        self.output.value = self.node.get_actual_position()


class RotaryMotor(Motor):
    def __init__(self, nodeId, *args, **kwargs):
        raise NotImplementedError
        # TODO: Make me!


class WindupMotor(Motor):
    def __init__(self, nodeId, *args, **kwargs):
        raise NotImplementedError
        # TODO: Make me!


class DummyMotor(Motor):

    """Dummy motor for testing and standalone usage."""

    def __init__(self, length=0.04):
        super().__init__()
        self.length = length
        self.state = KinematicState()
        self.dt = CONFIG['General']['INTERVAL']
        self.homed = HomingState.HOMED

    def update(self):
        # Kinematic filter input target position
        self.state = kinematic_filter(
            self.input.value,
            dt=self.dt,
            state=self.state,
            maxSpeed=1.,
            maxAcc=1.,
            lower=0.,
            upper=self.length,
        )

        self.output.value = self.state.position
