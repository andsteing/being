"""Miscellaneous blocks."""
# TODO: Renaming this module? Almost name conflict with block.py?
import math

from being.block import Block
from being.config import INTERVAL
from being.constants import TAU


class Sine(Block):

    """Sine generator. Outputs sine wave for a given frequency."""

    def __init__(self, frequency: float = 1., startPhase: float = 0.):
        """Kwargs:
            frequency: Initial frequency value.
            startPhase: Inital phase.
        """
        super().__init__()
        self.phase = startPhase
        self.add_value_input('frequency')
        self.add_value_output()
        self.frequency.value = frequency

    def update(self):
        self.output.value = math.sin(self.phase)
        self.phase += TAU * self.frequency.value * INTERVAL
        self.phase %= TAU

    def __str__(self):
        return f'{type(self).__name__}(frequency={self.frequency.value:.1f} Hz)'


class Trafo(Block):

    """Transforms input signal (by some fixed scale and offset)."""

    def __init__(self, scale: float = 1., offset: float = 0.):
        """Kwargs:
            scale: Scaling factor.
            offset: Offset factor.
        """
        super().__init__()
        self.scale = scale
        self.offset = offset
        self.add_value_input()
        self.add_value_output()

    def update(self):
        self.output.value = self.scale * self.input.value + self.offset

    def __str__(self):
        return f'{type(self).__name__}(scale={self.scale:.3f}, offset={self.offset:.3f})'
