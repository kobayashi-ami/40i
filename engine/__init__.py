"""1260 DSP engine.

Every stage is a pure function on numpy arrays. Every parameter that is not settled by a source is a
HYPOTHESIS with switchable candidates (see `engine.params` and docs/research.md). Rendering is deterministic:
the same input and the same parameters give byte-identical output.
"""

from fractions import Fraction

# SP-1200 sample clock: 10 MHz / 384 = 20 MHz / 768. Kept exact so resampling ratios are exact.
SP_NATIVE_SR = Fraction(625000, 24)  # 26041.666… Hz
MPC_NATIVE_SR = Fraction(40000)

ENGINE_VERSION = "0.2.0"
