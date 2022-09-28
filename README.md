# Site Schedule Optimization

This project provides a tool to generate an optimized schedule for scientists that work out in the field, particularly those who need to schedule and visit many different locations ("sites") by car. For example, this could be utilized by ecologists taking stream sample data, or elevation measurements, etc, and have dozens of locations they need to visit. This tool uses the BING Maps API to load travel times between all pairs of your sites, then applies a Monte Carlo optimization method to generate a schedule minimizing the travel time.

The functionality is packaged in two forms:
1) QGIS plugin
2) Python CLI

## Method

In spirit, this problem is just the classic traveling-salesman problem (TSP), but with a few added constraints. In the typical TSP, one seeks a single route through a list of locations. Here, this route is broken up into multiple legs ("days"), each of which starts and ends at a "home base". So not only do we optimize for the order but also, which sites belong in the same outings to globally minimize travel time. This introduces the first extra constraint, `max sites per day`, which caps how many sites can be scheduled for a single day, and subsequently, the length of your schedule in days is actually a result of running the algorithm.

Optimization is done using simulated annealing, in which a ficticous temperature is slowly lowered whilst random perturbations are made to the current "state", i.e. current schedule. In each step each degree of freedom (which site is scheduled on which day) is attempted a random switch with another. This type of quantity conserving Monte Carlo is called "Kawasaki Dynamics". A probabilty to accept the change is computed using the delta in the global cost value and the current annealing parameter value. Swaps that lower the global cost function are always accepted but those that raise the global cost are stochastically accepted. As the annealing parameter lowers, these "uphill" perturbations become less and less likely to be accepted, forcing the solution to converge to a minimum. Starting from a sufficently large annealing parameter value ensures the actual global minimum of the cost function is approached.

More can be found here:
- https://en.wikipedia.org/wiki/Simulated_annealing
- https://en.wikipedia.org/wiki/Travelling_salesman_problem
- https://link.springer.com/chapter/10.1007/978-3-319-24777-9_18


## QGIS Plugin

The plugin is available in the public QGIS plugin repository (WILL ADD LINK).

Or if you are more developer savy, you can install the plugin yourself from this source code.

### Requirements

The plugin depends on other python packages.

- Numpy

Installing python packages is specific to the platform you run the QGIS on. For details, https://packaging.python.org/en/latest/tutorials/installing-packages/. The set of required python packages can also be found in `requirements.qgis.txt`.

<!-- The tool contains functionality to install its own python dependencies into an isolated location inside the QGIS plugin installation directory. This is the recommended way to install dependencies, as we can ensure the proper versions are available. But to install those, **`pip` is required to be available on your system** (by the python QGIS uses).

Install Pip: https://pip.pypa.io/en/stable/installation/

When you run the plugin, it will detect when you have not installed the required python dependences and provide a dialog which you can use to install them. Please refer to the Python error or SiteScheduleOptimization logs if you encounter errors, and include those when creating issues on this repository. -->

### Installing from Source

To install from source, there are two options: 1) Using `make deploy` which directly copies files into the python plugin directory of your QGIS installion, or 2) `make pb_deploy` which uses a helper tool `pb_tool` to do roughly the same thing. The latter is recommended but requires installing extra python dependencies from `requirements.dev.txt`. Those can be installed with `make install-dev`.


## Python CLI

The solver can be utilized from the command line directly via a CLI exposed in the script `run.py`. The makefile contains several examples but here is the full CLI surface.

```
$ python run.py --help
Usage: run.py [OPTIONS]

  Find a multi-day schedule optimizer for visiting survey locations.

Options:
  -i, --site-data TEXT            CSV file containing sites metadata.
                                  [required]
  -c, --cost-data TEXT            CSV file containing pairwise cost data.
  -o, --output TEXT               Base name of output files.  [default:
                                  results]
  -u, --max-stops-per-day INTEGER
                                  Maximum number of sites to visit per day.
                                  [default: 5]
  -n, --annealing-iters INTEGER   Number of annealing iterations. Each step
                                  all dofs are attempted to swap.  [default:
                                  20000]
  -q, --quiet                     Silence verbose output
  --bing-maps-api-key TEXT        Bing Maps API Key used to auto-generate cost
                                  matrix using distances.  [default: None]
  --bing-travel-mode [driving|walking]
                                  Bing Maps API Key used to auto-generate cost
                                  matrix using distances.  [default: driving]
  --cost-type [distance|time]     Compute cost matrix using distances or
                                  travel time.  [default: time]
  -s, --start-datetime TEXT       The date and time of the begin of the
                                  schedule.
  -dc, --disable-cache            Disables any caching.
  -iN, --ignore-node-cost         Ignores the node cost values during
                                  calculation caching.
  --help                          Show this message and exit.
```

It's worth pointing out that via the CLI you can provide your own "cost matrix" instead of
using BING Maps API.


### Requirements

Requirements to run the CLI are in `requirements.txt` and can be installed using Make. Its recommended to use and activate a python virtual environment. Install the requirements with,
```
make install
```
