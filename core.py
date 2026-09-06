"""
core.py is the computational core of lab 1.

KEY PRINCIPLE OF THE EXPERIMENT:
This module is used WITHOUT ANY CHANGES in all three stages:
Stage 1 - direct function call;
Stage 2 - call inside the FastAPI web service;
Stage 3 - the same web service inside the Docker container.
Due to this, all the difference in execution time
is the overhead of the architecture, and not the difference in the algorithm implementation.

The implementation is intentionally done without external libraries (NumPy, etc.)
so that the computation time is deterministic and does not depend on
vectorized optimizations of third-party packages.
"""

import random
import math
from typing import List, Dict, Any

ARRAY_SEED = 42


def generate_array(size: int, seed: int = ARRAY_SEED) -> List[float]:
    """
    Generates a reproducible array of pseudo-random numbers.

    A fixed seed ensures that all three stages are fed IDENTICAL input data.

    :param size: number of array elements
    :param seed: seed of the pseudo-random number generator
    :return: list of real numbers in the range [0, 1000)
    """
    rng = random.Random(seed)
    return [rng.uniform(0.0, 1000.0) for _ in range(size)]


def process_array(data: List[float]) -> Dict[str, Any]:
    """
    The basic data processing algorithm studied in the work:
    calculation of statistical characteristics of the array;

    Computational complexity: O(n log n) — due to sorting for the median.

    :param data: input array of numbers
    :return: dictionary with calculation results
    """
    n = len(data)
    if n == 0:
        raise ValueError("Вхідний масив порожній")

    # --- Блок 1: базові статистичні характеристики ---
    total = 0.0
    minimum = data[0]
    maximum = data[0]
    for value in data:
        total += value
        if value < minimum:
            minimum = value
        if value > maximum:
            maximum = value
    mean = total / n

    # --- Блок 2: дисперсія та стандартне відхилення ---
    sum_sq_diff = 0.0
    for value in data:
        diff = value - mean
        sum_sq_diff += diff * diff
    variance = sum_sq_diff / n # дисперсія
    std_dev = math.sqrt(variance) # стандартне відхилення

    # --- Блок 3: медіана (потребує сортування) ---
    ordered = sorted(data)
    mid = n // 2
    if n % 2 == 0:
        median = (ordered[mid - 1] + ordered[mid]) / 2.0
    else:
        median = ordered[mid]

    return {
        "count": n,
        "mean": mean,
        "median": median,
        "std_dev": std_dev,
        "min": minimum,
        "max": maximum,
    }
