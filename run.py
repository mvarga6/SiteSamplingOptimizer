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

import datetime
import hashlib
import json
import os
import pathlib
import pprint

import click
import dateutil.parser
import humanize
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests

from solver import daily_cost, solve


def in_range(low, high):
    def validate_range(ctx, param, value):
        if not (low <= value <= high):
            raise click.BadParameter(
                f"{value} needs to be in range [{low}, {high}]", ctx, param
            )
        return value

    return validate_range


def parse_datetime_str(ctx, param, value):
    if value is None:
        return None
    try:
        dt = dateutil.parser.parse(value)
        if dt.tzinfo is None:
            # Attach current time zone if not present
            dt = dt.astimezone()
        return dt
    except Exception:
        raise click.BadParameter(
            f"Could not parse datetime from '{value}' ", ctx, param
        )


@click.command(
    name="solve",
    help="Find a multi-day schedule optimizer for visiting survey locations.",
    context_settings={"show_default": True},
)
@click.option(
    "-i",
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
    "output_base",
    default="results",
    type=str,
    help="Base name of output files.",
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
    help="Number of annealing iterations. Each "
    + "step all dofs are attempted to swap.",
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
    "--cost-type",
    "cost_type",
    default="time",
    type=click.Choice(["distance", "time"]),
    help="Compute cost matrix using distances or travel time.",
)
@click.option(
    "-s",
    "--start-datetime",
    "start_datetime",
    default=None,
    type=str,
    callback=parse_datetime_str,
    help="The date and time of the begin of the schedule.",
)
@click.option(
    "-dc",
    "--disable-cache",
    is_flag=True,
    help="Disables any caching.",
)
@click.option(
    "-iN",
    "--ignore-node-cost",
    is_flag=True,
    help="Ignores the node cost values during calculation caching.",
)
def cli(
    sites_file,
    costs_file,
    output_base,
    max_stops_per_day,
    annealing_iters=20000,
    quiet=False,
    bing_maps_api_key=None,
    bing_travel_mode="driving",
    cost_type="time",
    start_datetime=None,
    disable_cache=False,
    ignore_node_cost=False,
):
    verbose = not quiet
    print_interval = annealing_iters // 10

    sites, C_node = load_sites_file(sites_file, ignore_node_cost)

    if verbose:
        print("sites =")
        pprint.pprint(sites, indent=4)

    if costs_file:
        C_edge = load_costs_file(costs_file, cost_type)
    elif bing_maps_api_key:
        if not _check_can_use_bing(sites):
            raise click.BadArgumentUsage(
                """
                Site data read from '{}' does not support using BING maps API
                for cost matrix computation. Confirm there are latitude and
                longitude columns and values specified for each record.
                """.format(
                    sites_file
                )
            )
        C_edge = get_bing_maps_edge_costs(
            sites=sites,
            travel_mode=bing_travel_mode,
            cost_type=cost_type,
            start_time=start_datetime,
            api_key=bing_maps_api_key,
            force=disable_cache,
        )
    else:
        raise click.BadArgumentUsage(
            """
            Must pass either a cost matrix using '--costs-data' option or use
            the BING Maps API to compute a cost matrix by using
            '--bing-maps-api-key', '--bing-travel-mode', and '--bing-cost'
            options.

            You can also set the environmental variable `BING_MAPS_API_KEY`.
            """
        )

    if len(C_edge) != len(sites):
        raise click.BadArgumentUsage(
            """
            The sites data and costs data do not contain the same
            number of sites. There are {} in {}, but {} refers to {}.
            """.format(
                len(sites), sites_file, costs_file, len(C_edge)
            )
        )

    def pre_solve_callback(initial_state):
        if verbose:
            print("initial_state =")
            pprint.pprint(initial_state)
            print("C_edge =")
            pprint.pprint(C_edge)
            print("C_node =")
            pprint.pprint(C_node)

    def post_iter_callback(i, cost_history, annealing_param):
        if verbose and i % print_interval == print_interval - 1:
            mean_cost = np.mean(cost_history[i - print_interval + 1 : i])
            print(
                "step={}, annealing_param={}, cost={}".format(
                    i + 1, round(annealing_param, 4), round(mean_cost, 4)
                )
            )

    parameters = {
        "max_stops_per_day": max_stops_per_day,
        "annealing_iters": annealing_iters,
        "verbosity": int(verbose),
    }

    state, cost_history = solve(
        sites=sites,
        C_node=C_node,
        C_edge=C_edge,
        parameters=parameters,
        pre_solve_callback=pre_solve_callback,
        post_iteration_callback=post_iter_callback,
    )

    print_results(sites, state, cost_history, output_base, C_edge, C_node)
    write_results(sites, state, cost_history, output_base, C_edge, C_node)


def print_results(sites, state, cost_history, output_base, C_edge, C_node):
    print("======== SOLUTION =========")
    for day_i, stops in enumerate(state):
        cost_disp = humanize.precisedelta(
            value=datetime.timedelta(minutes=daily_cost(C_edge, C_node, stops)),
            minimum_unit="minutes",
        )
        print("Day {} ({})".format(day_i + 1, cost_disp))
        for j, site_j in enumerate(stops[stops >= 0]):
            print(f"{j+1}.", sites[site_j]["name"])
        print()
    print("===========================")


def write_results(sites, state, cost_history, output_base, C_edge, C_node):
    df = pd.DataFrame(sites)
    day, stop = [0], [0]
    for site_i in range(1, len(sites)):
        day_i, stop_i = np.where(state == site_i)
        day.append(day_i[0] + 1)
        stop.append(stop_i[0] + 1)

    df["day"] = day
    df["stop"] = stop

    df.to_csv(output_base + ".csv", index=False)
    n_steps = len(cost_history)
    plt.plot(
        np.linspace(0, n_steps, num=n_steps), cost_history, label="Travel Time"
    )
    plt.xlabel("Optimization Step")
    plt.ylabel("Total Travel Time")
    plt.title("Site Schedule Optimization")
    plt.legend()
    plt.savefig(output_base + ".png")


def load_sites_file(filepath, ignore_node_cost):
    import pandas as pd

    df = pd.read_csv(filepath)
    costs = np.zeros(len(df))
    if "cost" in df.columns and not ignore_node_cost:
        costs = df["cost"].values
    return df.to_dict(orient="records"), costs


def load_costs_file(filepath, cost_type):
    import pandas as pd

    df = pd.read_csv(filepath)
    i = df["site_1"].values
    j = df["site_2"].values
    n_sites = np.unique(np.concatenate((i, j))).size
    C = np.zeros(shape=(n_sites, n_sites))
    C[i, j] = df[cost_type].values
    return C


def get_bing_maps_edge_costs(
    sites,
    travel_mode,
    cost_type,
    api_key,
    start_time=None,
    force=False,
):
    # Caching saves us from making the same requests
    # over and over during testing and development.
    _cache_dir = pathlib.Path(os.path.dirname(__file__)) / ".cache"

    def _cache_key(d):
        return hashlib.md5(json.dumps(d).encode()).hexdigest()

    def _write_cache(key, resp_json):
        if not _cache_dir.exists():
            _cache_dir.mkdir()
        cache_file = _cache_dir / f"{key}.json"
        cache_file.write_text(json.dumps(resp_json))

    def _read_cache(key):
        cache_file = _cache_dir / f"{key}.json"
        if not force and cache_file.exists():
            print("BING Matrix read from cache")
            return json.loads(cache_file.read_text())
        return None

    url = "https://dev.virtualearth.net"
    url += "/REST/v1/Routes/DistanceMatrix"
    url += f"?key={api_key}"

    payload = {
        "travelMode": travel_mode,
        "origins": sites,
        "destinations": sites,
    }

    if start_time is not None:
        payload["startTime"] = start_time.isoformat()

    cache_key = _cache_key(payload)
    data = _read_cache(cache_key)
    if data is None:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        _write_cache(cache_key, data)

    C = np.zeros((len(sites), len(sites)))
    for edge in data["resourceSets"][0]["resources"][0]["results"]:
        i, j = edge["originIndex"], edge["destinationIndex"]
        C[i, j] = (
            edge["travelDuration"]
            if travel_mode == "time"
            else edge["travelDistance"]
        )

    return C


def _check_can_use_bing(sites):
    for site in sites:
        if (
            not isinstance(site, dict)
            or not isinstance(site.get("longitude"), (int, float))
            or not isinstance(site.get("latitude"), (int, float))
        ):
            return False
    return True


if __name__ == "__main__":
    cli()
