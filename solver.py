# -*- coding: utf-8 -*-
"""
/***************************************************************************
 SiteScheduleOptimization

                    A simulated annealing Monte Carlo optimizer.
 Finds an optimal multi-day schedule for traveling to a set of locations.

                              -------------------
        begin                : 2022-08-09
        git sha              : $Format:%H$
        copyright            : (C) 2022 by Mike Varga
        email                : mvarga6@kent.edu
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import itertools
import math

import numpy as np


def solve(
    sites,
    C_node,
    C_edge,
    parameters,
    pre_solve_callback=None,
    post_iteration_callback=None,
):

    max_stops_per_day = parameters["max_stops_per_day"]
    annealing_iters = parameters["annealing_iters"]

    n_sites = len(sites)
    n_days = math.ceil(n_sites / max_stops_per_day)
    n_slots = max_stops_per_day * n_days

    # Initialize the state
    state = initial_state(n_sites, n_days, max_stops_per_day)

    # Build the schedule for the annealing parameter
    annealing_scale = total_cost(C_edge, C_node, state)
    annealing_schedule = annealing_scale * np.logspace(
        start=0, stop=20, num=annealing_iters, base=0.5
    )

    #
    # Functions for manipulating state during annealing
    #

    def swap(day1, stop1, day2, stop2):
        """Swap the two stops"""
        tmp = state[day1, stop1]
        state[day1, stop1] = state[day2, stop2]
        state[day2, stop2] = tmp

    def probability(dC, T):
        """Compute a hypothetical probability of a transition to a
        higher cost state.
        """
        return math.exp(-dC / T)

    def rand_dofs():
        """Returns tuple of day indices, stop indices to index directly
        into the state matrix.
        """
        return (
            np.random.randint(0, n_days, size=n_slots),
            np.random.randint(1, 1 + max_stops_per_day, size=n_slots),
            np.random.randint(0, n_days, size=n_slots),
            np.random.randint(1, 1 + max_stops_per_day, size=n_slots),
        )

    if pre_solve_callback:
        pre_solve_callback(state)

    #
    # Perform the simulated annealing
    #

    cost_history = np.empty(annealing_schedule.shape)

    for i, annealing_param in enumerate(annealing_schedule):
        for (day1, stop1, day2, stop2) in zip(*rand_dofs()):
            C1 = daily_cost(C_edge, C_node, state[day1])
            C1 += daily_cost(C_edge, C_node, state[day2])
            swap(day1, stop1, day2, stop2)
            C2 = daily_cost(C_edge, C_node, state[day1])
            C2 += daily_cost(C_edge, C_node, state[day2])
            dC = C2 - C1

            # Stochastically keep (+) change in E (total cost).
            # As temperature lowers, (+) changes become less probable.
            # Implemented by "reversing the swap".
            if probability(dC, annealing_param) <= np.random.uniform(0, 1):
                swap(day1, stop1, day2, stop2)

        cost_history[i] = total_cost(C_edge, C_node, state)

        if post_iteration_callback:
            keep_running = post_iteration_callback(
                i, cost_history, annealing_param
            )
            if not keep_running:
                return state, cost_history

    return state, cost_history


def initial_state(n_sites, n_days, max_stops_per_day):
    """Get an initial solution guess, i.e. initial state

    First index is day, second index is stop of that day.
    The first and last stops of each day of constrained to
    be 0, the home state.

    Values:
      -1: Masked, 0: home site: 1+: site_id

    - Fill slots with integers
    - Mask slots w/ values > max site index
    - Randomize
    - Add zero buffer (home index) on front and back of each day
    """
    n_slots = n_days * max_stops_per_day
    slots = np.arange(0, n_slots).reshape(n_days, max_stops_per_day) + 1
    slots[slots >= n_sites] = -1
    np.random.shuffle(slots)
    zero_buf = np.zeros((n_days, 1))
    return np.hstack((zero_buf, slots, zero_buf)).astype(int)


def daily_cost(C_edge, C_node, stops):
    path = stops[stops > -1]
    edges_cost = sum(C_edge[i, j] for i, j in _pairs(path))
    nodes_cost = sum(C_node[i] for i in path) if C_node is not None else 0
    return edges_cost + nodes_cost


def total_cost(C_edge, C_node, state):
    return sum(daily_cost(C_edge, C_node, stops) for stops in state)


def _pairs(iterable):
    "s -> (s0, s1), (s1, s2), (s2, s3), ..."
    a, b = itertools.tee(iterable)
    next(b, None)
    return zip(a, b)
