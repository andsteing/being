"""Motor controllers."""
import abc
import sys
import warnings
from typing import Optional, Set, List

from canopen.emcy import EmcyError

from being.bitmagic import clear_bit, set_bit
from being.can.cia_402 import CiA402Node, HOMING_METHOD, OperationMode, State, StateSwitching
from being.configuration import CONFIG
from being.constants import FORWARD
from being.logging import get_logger
from being.math import clip
from being.motors.definitions import MotorInterface, MotorState, MotorEvent, PositionProfile, VelocityProfile
from being.motors.homing import CiA402Homing, CrudeHoming, default_homing_method
from being.motors.motors import Motor
from being.motors.vendor import (
    FAULHABER_EMERGENCY_DESCRIPTIONS,
    FAULHABER_SUPPORTED_HOMING_METHODS,
    MAXON_EMERGENCY_DESCRIPTIONS,
    MAXON_SUPPORTED_HOMING_METHODS,
    MaxonDigitalInput,
)
from being.utils import merge_dicts


INTERVAL = CONFIG['General']['INTERVAL']
LOGGER = get_logger(name=__name__, parent=None)


def nested_get(dct, keys):
    """Nested dict access."""
    for k in keys:
        dct = dct[k]

    return dct


def inspect(node, name):
    """Inspect node setting / parameter by name."""
    e = nested_get(node.sdo, name.split('/'))
    print(name, e.raw)


def inspect_many(node, names):
    """Inspect many node settings / parameters by name."""
    for name in names:
        inspect(node, name)


def format_error_code(errorCode: int, descriptions: list) -> str:
    """Emergency error code -> description.

    Args:
        errorCode: Error code to check.
        descriptions: Description table with (code, mask, description) entries.

    Returns:
        Text error description.
    """
    description = 'Unknown emergency error'
    for code, mask, desc in descriptions:
        if errorCode & mask == code:
            description = desc

    return f'{description} (error code {errorCode:#04x})'


class Controller(MotorInterface):

    """Semi abstract controller base class.

    Implements general, non-vendor specific, controller functionalities.
      - Configuring and managing of CanOpen node.
      - Homing
      - Target position clipping range.
      - Drives node state switch jobs (for asynchronous state changes).
      - SI <-> device units conversion.
      - Relaying EMCY errors.

    Attributes:
        node (CiA402Node): Connected CiA 402 CANopen node.
        motor (Motor): Associated hardware motor.
        direction (float): Motor direction.
        length (float): Length of motor.
        logger (Logger): Controller logger instance.
        position_si_2_device (float): SI position to device units conversion factor.
        velocity_si_2_device (float): SI velocity to device units conversion factor.
        acceleration_si_2_device (float): SI acceleration to device units conversion factor.
        lower (int): Lower clipping value for target position in device units.
        upper (int): Upper clipping value for target position in device units.
        lastState (being.can.cia_402.State): Last receive state of motor controller.
        switchJob (Optional[StateSwitching]): Ongoing state switching job.
    """

    EMERGENCY_DESCRIPTIONS: List[tuple] = []
    """List of (code (int), mask (int), description (str)) tuples with the error
    informations.
    """

    SUPPORTED_HOMING_METHODS: Set[int] = {}
    """Set of the supported homing method numbers for the controller."""

    def __init__(self,
            node: CiA402Node,
            motor: Motor,
            length: float,
            direction: int = FORWARD,
            settings: Optional[dict] = None,
            operationMode: OperationMode = OperationMode.CYCLIC_SYNCHRONOUS_POSITION,
            **homingKwargs,
        ):
        """Args:
            node: Connected CanOpen node.
            motor: Motor definitions / settings.
            length: Clipping length in SI units.
            direction: Movement direction.
            settings: Motor settings.
            operationMode: Operation mode for node.
            **homingKwargs: Homing parameters.
        """
        # Defaults
        if settings is None:
            settings = {}

        super().__init__()

        # Attrs
        self.node: CiA402Node = node
        self.motor: Motor = motor
        self.direction = direction
        self.length = length

        self.logger = get_logger(str(self))
        self.position_si_2_device = motor.si_2_device_units('position')
        self.velocity_si_2_device = motor.si_2_device_units('velocity')
        self.acceleration_si_2_device = motor.si_2_device_units('acceleration')
        self.lower = 0.
        self.upper = length * self.position_si_2_device
        self.lastState = node.get_state()
        self.switchJob = None

        # Prepare settings
        self.settings = merge_dicts(self.motor.defaultSettings, settings)

        self.init_homing(**homingKwargs)

        # Possible fault reset
        self.node.change_state(State.SWITCH_ON_DISABLED, 'sdo')

        # Configure node
        self.apply_motor_direction(direction)
        self.node.apply_settings(self.settings)
        for errMsg in self.error_history_messages():
            self.logger.error(errMsg)

        self.disable()
        self.node.set_operation_mode(operationMode)

    def disable(self):
        self.switchJob = self.node.state_switching_job(State.READY_TO_SWITCH_ON, how='pdo')

    def enable(self):
        self.switchJob = self.node.state_switching_job(State.OPERATION_ENABLED, how='pdo')

    def motor_state(self):
        if self.lastState is State.OPERATION_ENABLED:
            return MotorState.ENABLED
        elif self.lastState is State.FAULT:
            return MotorState.FAULT
        else:
            return MotorState.DISABLED

    def home(self):
        """Create homing job routine for this controller."""
        self.logger.debug('home()')
        self.homing.home()
        self.publish(MotorEvent.HOMING_CHANGED)

    def homing_state(self):
        return self.homing.state

    def init_homing(self, **homingKwargs):
        """Setup homing. Done here and not directly in __init__ so that child
        class can overwrite this behavior.

        Args:
            **homingKwargs: Homing parameters.
        """
        method = default_homing_method(**homingKwargs)
        if method not in self.SUPPORTED_HOMING_METHODS:
            raise ValueError(f'Homing method {method} not supported for controller {self}')

        self.homing = CiA402Homing(self.node)
        self.node.sdo[HOMING_METHOD].raw = method

    @abc.abstractmethod
    def apply_motor_direction(self, direction: float):
        """Configure direction or orientation of controller / motor."""
        raise NotImplementedError

    def format_emcy(self, emcy: EmcyError) -> str:
        """Get vendor specific description of EMCY error."""
        return format_error_code(emcy.code, self.EMERGENCY_DESCRIPTIONS)

    def error_history_messages(self):
        """Iterate over current error messages in error history register."""
        errorHistory = self.node.sdo[0x1003]
        numErrors = errorHistory[0].raw
        for nr in range(numErrors):
            number = errorHistory[nr + 1].raw
            raw = number.to_bytes(4, sys.byteorder)
            code = int.from_bytes(raw[:2], 'little')
            yield format_error_code(code, self.EMERGENCY_DESCRIPTIONS)

    def set_target_position(self, targetPosition):
        """Set target position in SI units."""
        if self.homing.homed:
            dev = targetPosition * self.position_si_2_device
            clipped = clip(dev, self.lower, self.upper)
            self.node.set_target_position(clipped)

    def get_actual_position(self) -> float:
        """Get actual position in SI units."""
        return self.node.get_actual_position() / self.position_si_2_device

    def play_position_profile(self, profile: PositionProfile):
        """Play position profile."""
        pos = self.position_si_2_device * profile.position
        vel = None
        acc = None

        if profile.velocity is not None:
            vel = self.velocity_si_2_device * profile.velocity

        if profile.acceleration is not None:
            acc = self.acceleration_si_2_device * profile.acceleration

        self.node.move_to(position=pos, velocity=vel, acceleration=acc)

    def play_velocity_profile(self, profile: VelocityProfile):
        """Play velocity profile."""
        vel = self.velocity_si_2_device * profile.velocity
        acc = None

        if profile.acceleration is not None:
            acc = self.acceleration_si_2_device * profile.acceleration

        self.node.move_with(velocity=vel, acceleration=acc)

    def state_changed(self, state: State) -> bool:
        """Check if node state changed since last call."""
        if state is self.lastState:
            return False

        self.lastState = state
        return True

    def publish_errors(self):
        """Publish all active EMCY errors. Active error messages get discard
        afterwards.
        """
        for emcy in self.node.emcy.active:
            msg = self.format_emcy(emcy)
            self.logger.error(msg)
            self.publish(MotorEvent.ERROR, msg)

        self.node.emcy.reset()

    def update(self):
        """Controller tick function. Does the following:
          - Observe state changes and publish
          - Observe errors and publish
          - Drive homing
          - Drive state switching jobs
        """
        state = self.node.get_state('pdo')
        if self.state_changed(state):
            self.publish(MotorEvent.STATE_CHANGED)

        if state is State.FAULT:
            self.publish_errors()

        if self.homing.ongoing:
            self.homing.update()
            if not self.homing.ongoing:
                self.publish(MotorEvent.HOMING_CHANGED)
        elif self.switchJob:
            try:
                next(self.switchJob)
            except StopIteration:
                self.switchJob = None
            except TimeoutError as err:
                self.logger.exception(err)
                self.switchJob = None

    def __str__(self):
        return f'{type(self).__name__}({self.node}, {self.motor})'


class Mclm3002(Controller):

    """Faulhaber MCLM 3002 controller.

    This controller does not support the unofficial max current based hard stop
    homing methods. We monkey patch a CrudeHoming for these cases, which
    implements the same behavior.
    """

    EMERGENCY_DESCRIPTIONS = FAULHABER_EMERGENCY_DESCRIPTIONS
    SUPPORTED_HOMING_METHODS = FAULHABER_SUPPORTED_HOMING_METHODS
    HARD_STOP_HOMING = {-1, -2, -3, -4}

    def __init__(self,
            *args,
            homingMethod: Optional[int] = None,
            homingDirection: float = FORWARD,
            operationMode: OperationMode = OperationMode.CYCLIC_SYNCHRONOUS_POSITION,
            **kwargs,
        ):
        super().__init__(
            *args,
            homingMethod=homingMethod,
            homingDirection=homingDirection,
            operationMode=operationMode,
            **kwargs,
        )

    def init_homing(self, **homingKwargs):
        method = default_homing_method(**homingKwargs)
        if method in self.HARD_STOP_HOMING:
            minWidth = self.position_si_2_device * self.length
            currentLimit = self.settings['Current Control Parameter Set/Continuous Current Limit']
            self.homing = CrudeHoming(self.node, minWidth, homingMethod=method, currentLimit=currentLimit)
        else:
            super().init_homing(homingMethod=method)

    def apply_motor_direction(self, direction: float):
        if direction >= 0:
            positivePolarity = 0
            self.node.sdo['Polarity'].raw = positivePolarity
        else:
            negativePolarity = (1 << 6) | (1 << 7)  # Position and velocity
            self.node.sdo['Polarity'].raw = negativePolarity


class Epos4(Controller):

    """Maxon EPOS4 controller.

    This controllers goes into an error state when RPOD / SYNC messages are not
    arriving on time -> recoverRpdoTimeoutError which re-enables the motor when
    the RPOD timeout error occurs.

    Also a simple, alternative position controller which sends velocity
    commands.

    Todo:
        Testing if ``firmwareVersion < 0x170h``?

    """

    EMERGENCY_DESCRIPTIONS = MAXON_EMERGENCY_DESCRIPTIONS
    SUPPORTED_HOMING_METHODS = MAXON_SUPPORTED_HOMING_METHODS

    def __init__(self,
            node: CiA402Node,
            *args,
            usePositionController: bool = True,
            recoverRpdoTimeoutError: bool = True,
            operationMode: OperationMode = OperationMode.CYCLIC_SYNCHRONOUS_POSITION,
            **kwargs,
        ):
        """Args:
            usePositionController: If True use position controller on EPOS4 with
                operation mode CYCLIC_SYNCHRONOUS_POSITION. Otherwise simple
                custom application side position controller working with the
                CYCLIC_SYNCHRONOUS_VELOCITY.
            recoverRpdoTimeoutError: Re-enable drive after a FAULT because of a
                RPOD timeout error.
        """
        if not usePositionController:
            warnings.warn(
                'Setting operation mode to'
                f' {OperationMode.CYCLIC_SYNCHRONOUS_VELOCITY} for custom'
                ' position controller'
            )
            operationMode = OperationMode.CYCLIC_SYNCHRONOUS_VELOCITY

        self.set_all_digital_inputs_to_none(node)  # Before apply_settings_to_node
        super().__init__(node, *args, operationMode=operationMode, **kwargs)
        self.usePositionController = usePositionController
        self.recoverRpdoTimeoutError = recoverRpdoTimeoutError
        self.rpdoTimeoutOccurred = False

        self.logger.info('Firmware version 0x%04x', self.firmware_version())

    def init_homing(self, **homingKwargs):
        method = default_homing_method(**homingKwargs)
        if method == 35:
            warnings.warn('Epos4 does not support homing method 35. Using 37 instead.')
            method = 37

        super().init_homing(homingMethod=method)

    def firmware_version(self) -> int:
        """Firmware version of EPOS4 node."""
        revisionNumber = self.node.sdo['Identity object']['Revision number'].raw
        lowWord = 16
        firmwareVersion = revisionNumber >> lowWord
        return firmwareVersion

    def apply_motor_direction(self, direction: float):
        variable = self.node.sdo['Axis configuration']['Axis configuration miscellaneous']
        misc = variable.raw
        if direction >= 0:
            newMisc = clear_bit(misc, bit=0)
        else:
            newMisc = set_bit(misc, bit=0)

        variable.raw = newMisc

    @staticmethod
    def set_all_digital_inputs_to_none(node):
        """Set all digital inputs of Epos4 controller to none by default.
        Reason: Because of settings dictionary it is not possible to have two
        entries. E.g. unset and then set to HOME_SWITCH.
        """
        for subindex in range(1, 9):
            node.sdo['Configuration of digital inputs'][subindex].raw = MaxonDigitalInput.NONE

    def set_target_position(self, targetPosition):
        if self.homing.homed:
            dev = targetPosition * self.position_si_2_device
            posSoll = clip(dev, self.lower, self.upper)

            if self.usePositionController:
                self.node.set_target_position(posSoll)
            else:
                posIst = self.node.get_actual_position()
                self.node.set_target_position(posSoll)
                err = (posSoll - posIst)
                velSoll = 1e-3 / INTERVAL * err
                self.node.set_target_velocity(velSoll)

    def publish_errors(self):
        for emcy in self.node.emcy.active:
            rpodTimeout = 0x8250
            if emcy.code == rpodTimeout:
                self.rpdoTimeoutOccurred = True

            msg = self.format_emcy(emcy)
            self.logger.error(msg)
            self.publish(MotorEvent.ERROR, msg)

        self.node.emcy.reset()

    def update(self):
        super().update()
        if self.recoverRpdoTimeoutError:
            if self.lastState is State.FAULT and self.rpdoTimeoutOccurred:
                self.enable()
                self.rpdoTimeoutOccurred = False
