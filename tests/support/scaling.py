"""Wall-clock checks that a busy CI runner cannot flake: best-of-N timings compared as growth ratios."""
from __future__ import annotations

import time
from collections.abc import Callable
from functools import partial

REPEATS = 3
SCALE_FACTOR = 4
# Linear work grows ~4x when its input grows 4x and quadratic work ~16x; 8 separates them with room for noise.
MAX_LINEAR_GROWTH = 8


def best_seconds(run: Callable[[], object], repeats: int = REPEATS) -> float:
    """Fastest of several runs, so a load spike on a shared runner cannot inflate the measurement."""
    timings: list[float] = []
    for _ in range(repeats):
        start = time.perf_counter()
        run()
        timings.append(time.perf_counter() - start)
    return min(timings)


def assert_linear_scaling(run_at_size: Callable[[int], object], size: int) -> None:
    """Fail when growing the input SCALE_FACTOR-fold grows the time super-linearly."""
    small = best_seconds(partial(run_at_size, size))
    large = best_seconds(partial(run_at_size, size * SCALE_FACTOR))
    assert large / small < MAX_LINEAR_GROWTH, f"{SCALE_FACTOR}x input took {large / small:.1f}x as long ({small:.3f}s -> {large:.3f}s)"
