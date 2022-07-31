import sys
import os
import math
import itertools
import pprint

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import click
import requests


def in_range(low, high):
    def validate_range(ctx, param, value):
        if not (low <= value <= high):
            raise click.BadParameter(
                f"{value} needs to be in range [{low}, {high}]", ctx, param
            )
        return value

    return validate_range


@click.command(
    name="solve",
    help="Find a multi-day schedule optimizer for visiting survey locations.",
    context_settings={"show_default": True},
)
@click.option(
    "-s",
    "--site-data",
    "sites_file",
    required=True,
    type=str,
    help="CSV file containing sites metadata.",
)
@click.option(
    "-c",
    "--cost-data",
    "costs_file",
    type=str,
    help="CSV file containing pairwise cost data.",
)
@click.option(
    "-o",
    "--output",
    "output_file",
    default="result.png",
    type=str,
    help="PNG file write output to",
)
@click.option(
    "-d",
    "--days",
    "n_days",
    default=5,
    type=int,
    callback=in_range(2, 365),
    help="Number of days to compute the schedule for.",
)
@click.option(
    "-l",
    "--min-stops-per-day",
    "min_stops_per_day",
    default=1,
    type=int,
    callback=in_range(1, 5),
    help="Minimum number of sites to visit per day.",
)
@click.option(
    "-u",
    "--max-stops-per-day",
    "max_stops_per_day",
    default=5,
    type=int,
    callback=in_range(2, 30),
    help="Maximum number of sites to visit per day.",
)
@click.option(
    "-n",
    "--annealing-iters",
    "annealing_iters",
    default=20000,
    type=int,
    callback=in_range(1e1, 1e7),
    help="Number of annealing iterations. Each step all dofs are attempted to swap.",
)
@click.option(
    "-b",
    "--annealing-param-decay",
    "annealing_param_decay",
    default=0.995,
    type=float,
    callback=in_range(0.9, 0.99999),
    help="Determines how fast the annealing occurs. ",
)
@click.option(
    "-q",
    "--quiet",
    is_flag=True,
    help="Silence verbose output",
)
@click.option(
    "--bing-maps-api-key",
    "bing_maps_api_key",
    default=os.environ.get("BING_MAPS_API_KEY"),
    type=str,
    help="Bing Maps API Key used to auto-generate cost matrix using distances.",
)
@click.option(
    "--bing-travel-mode",
    "bing_travel_mode",
    default="driving",
    type=click.Choice(["driving", "walking"]),
    help="Bing Maps API Key used to auto-generate cost matrix using distances.",
)
@click.option(
    "--bing-cost",
    "bing_cost",
    default="time",
    type=click.Choice(["distance", "time"]),
    help="Bing Maps API Key used to auto-generate cost matrix using distances.",
)
def find_optimal_scheduling(
    sites_file,
    costs_file,
    output_file,
    n_days,
    min_stops_per_day,
    max_stops_per_day,
    annealing_param_decay=0.995,
    annealing_iters=20000,
    quiet=False,
    bing_maps_api_key=None,
    bing_travel_mode="driving",
    bing_cost="time",
):
    verbose = not quiet

    sites = load_site_data(sites_file)

    if verbose:
        print("sites =")
        pprint.pprint(sites, indent=4)

    if costs_file:
        C = load_cost_data(costs_file)
    elif bing_maps_api_key:
        if not _check_can_use_bing(sites):
            raise click.BadArgumentUsage(
                """
                Site data read from '{}' does not support using BING maps API for
                cost matrix computation. Confirm there are latitude and longitude columns
                and values specified for each record.
                """.format(
                    sites_file
                )
            )
        C = bing_maps_cost_data(sites, bing_travel_mode, bing_cost, bing_maps_api_key)
    else:
        raise click.BadArgumentUsage(
            """
            Must pass either a cost matrix using '--costs-data' option or use
            the BING Maps API to compute a cost matrix by using '--bing-maps-api-key',
            '--bing-travel-mode', and '--bing-cost' options.
            """
        )

    if verbose:
        print("C =")
        pprint.pprint(C)

    n_sites = len(C)
    n_slots = max_stops_per_day * n_days
    print_interval = annealing_iters // 10

    if len(C) != len(sites):
        raise click.BadArgumentUsage(
            """
            The sites data and costs data do not contain the same number of sites.
            There are {} in {}, but {} refers to {}.
            """.format(
                len(sites), sites_file, costs_file, n_sites
            )
        )

    if n_slots < (n_sites - 1):
        raise click.BadArgumentUsage(
            """
            More sites than available scheduling slots. There are {} days X {} slots/day = {} slots
            but there are {} sites to schedule. Increase the number of days, or max_stops_per_day.
            """.format(
                n_days, max_stops_per_day, n_slots, n_sites
            )
        )

    # Initialize the state
    state = initial_state(n_sites, n_days, max_stops_per_day)

    if verbose:
        print("initial_state =\n", state)

    annealing_scale = total_cost(C, state)

    # Build the schedule for the annealing parameter
    annealing_schedule = annealing_scale * np.logspace(
        start=0, stop=1000, num=annealing_iters, base=annealing_param_decay
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
        """Compute a hypothetical probability of a transition to a higher cost state."""
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

    #
    # Perform the simulated annealing
    #

    cost_history = np.empty(annealing_schedule.shape)

    for i, annealing_param in enumerate(annealing_schedule):
        for (day1, stop1, day2, stop2) in zip(*rand_dofs()):
            C1 = daily_cost(C, state[day1]) + daily_cost(C, state[day2])
            swap(day1, stop1, day2, stop2)
            C2 = daily_cost(C, state[day1]) + daily_cost(C, state[day2])
            dC = C2 - C1

            # Stochastically keep (+) change in E (total cost).
            # As temperature lowers, (+) changes become less probable.
            # Implemented by "reversing the swap".
            if probability(dC, annealing_param) <= np.random.uniform(0, 1):
                swap(day1, stop1, day2, stop2)

        cost_history[i] = total_cost(C, state)
        if verbose and i % print_interval == print_interval - 1:
            mean_cost = np.mean(cost[i - print_interval + 1 : i])
            print(
                "step={}, annealing_param={}, cost={}".format(
                    i + 1, round(annealing_param, 4), round(mean_cost, 4)
                )
            )

    save_results(sites, state, cost_history, output_file)


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


def save_results(meta, state, cost, output_file):
    print("======== SOLUTION =========")
    for day_i, stops in enumerate(state):
        print("Day", day_i + 1)
        for j, site_j in enumerate(stops[stops >= 0]):
            print(f"{j+1}.", meta[site_j]["name"])
        print()
    print("===========================")

    plt.plot(np.linspace(0, len(cost), num=len(cost)), cost, label="Travel Time")
    plt.xlabel("Optimization Step")
    plt.ylabel("Total Travel Time")
    plt.title("Site Schedule Optimization")
    plt.legend()
    plt.savefig(output_file)


def load_site_data(filepath):
    return pd.read_csv(filepath).to_dict(orient="records")


def load_cost_data(filepath):
    df = pd.read_csv(filepath)
    i = df["site_1"].values
    j = df["site_2"].values
    n_sites = np.unique(np.concatenate((i, j))).size
    C = np.zeros(shape=(n_sites, n_sites))
    C[i, j] = df["cost"].values
    return C


def bing_maps_cost_data(sites, travel_mode, cost_property, api_key):
    try:
        url = (
            f"https://dev.virtualearth.net/REST/v1/Routes/DistanceMatrix?key={api_key}"
        )

        payload = {
            "travelMode": travel_mode,
            "origins": sites,
            "destinations": sites,
        }

        response = requests.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

        C = np.zeros((len(sites), len(sites)))

        for edge in data["resourceSets"][0]["resources"][0]["results"]:
            i, j = edge["originIndex"], edge["destinationIndex"]
            C[i, j] = (
                edge["travelDuration"]
                if travel_mode == "time"
                else edge["travelDistance"]
            )

        return C

    except Exception as ex:
        print()
        print(ex)
        print()
        print("\tBING Maps API call failed!")
        print()
        exit(1)


def _check_can_use_bing(sites):
    for site in sites:
        if (
            not isinstance(site, dict)
            or not isinstance(site.get("longitude"), (int, float))
            or not isinstance(site.get("latitude"), (int, float))
        ):
            return False
    return True


def _pairs(iterable):
    "s -> (s0, s1), (s1, s2), (s2, s3), ..."
    a, b = itertools.tee(iterable)
    next(b, None)
    return zip(a, b)


def daily_cost(pair_cost, stops):
    return sum(pair_cost[i, j] for i, j in _pairs(stops[stops > -1]))


def total_cost(pair_cost, state):
    return sum(daily_cost(pair_cost, stops) for stops in state)


if __name__ == "__main__":
    find_optimal_scheduling()
