# -*- coding: utf-8 -*-
"""
/***************************************************************************
 SiteScheduleOptimization

                                 A QGIS plugin
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

import hashlib
import json
import os
import pathlib
import time

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCategorizedSymbolRenderer,
    QgsFeature,
    QgsField,
    QgsMessageLog,
    QgsNetworkAccessManager,
    QgsPalLayerSettings,
    QgsProject,
    QgsRendererCategory,
    QgsSymbol,
    QgsTask,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt import QtGui, QtWidgets, uic
from qgis.PyQt.QtCore import QUrl, QUrlQuery, QVariant
from qgis.PyQt.QtNetwork import QNetworkRequest


FORM_CLASS, _ = uic.loadUiType(
    os.path.join(
        os.path.dirname(__file__), "site_schedule_optimization_dialog_base.ui"
    )
)
CACHE_DIR = pathlib.Path(os.path.dirname(__file__)) / ".cache"
MESSAGE_CATEGORY = "SiteScheduleOptimization"


class SiteScheduleOptimizationDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        """Constructor."""
        super(SiteScheduleOptimizationDialog, self).__init__(parent)
        self.setupUi(self)

    def reset(self):
        # Populate initial GUI
        self.layers = QgsProject.instance().layerTreeRoot().children()
        self.Input_SitesLayer.clear()
        self.Input_SitesLayer.addItems([layer.name() for layer in self.layers])
        self.Input_SitesLayer.setCurrentIndex(-1)
        self.Input_OutputLayerName.setText("schedule")
        self.Input_BingMapsApiKey.setText(self.read_api_key())
        self.Input_BingMapsApiKey.editingFinished.connect(self.save_api_key)

        self.Button_Run.setEnabled(False)
        self.Button_Run.clicked.connect(self.run)
        self.Input_SitesLayer.currentIndexChanged.connect(self.try_enable_run)
        self.Input_OutputLayerName.textChanged.connect(self.try_enable_run)
        self.Input_BingMapsApiKey.textChanged.connect(self.try_enable_run)

    def save_api_key(self):
        _write_cache(
            "bing_api_key", {"value": self.Input_BingMapsApiKey.text()}
        )

    def read_api_key(self):
        v = _read_cache("bing_api_key")
        if isinstance(v, dict):
            return v.get("value", "")
        return ""

    def try_enable_run(self):
        if (
            self.Input_SitesLayer.currentIndex() >= 0
            and self.Input_OutputLayerName.text() != ""
            and self.Input_BingMapsApiKey.text() != ""
        ):
            self.Button_Run.setEnabled(True)
        else:
            self.Button_Run.setEnabled(False)

    def run(self):
        self.task = SolverTask(*self.get_solver_inputs())
        self.task.taskCompleted.connect(self.on_task_ended)
        self.task.taskTerminated.connect(self.on_task_ended)
        QgsApplication.taskManager().addTask(self.task)

        # Update GUI for while running
        self.Input_SitesLayer.setEnabled(False)
        self.Button_Run.clicked.disconnect()
        self.Button_Run.clicked.connect(self.task.cancel)
        self.Button_Run.setText("Cancel")
        self.Button_Run.setIcon(QtGui.QIcon.fromTheme("media-playback-stop"))

    def on_task_ended(self):

        if self.task.success:
            self.create_output_layer(self.task.solution)

        # Update GUI post run
        self.Button_Run.clicked.disconnect()
        self.Button_Run.clicked.connect(self.run)
        self.Button_Run.setText("Run")
        self.Button_Run.setIcon(QtGui.QIcon.fromTheme("media-playback-start"))
        self.Input_SitesLayer.setEnabled(True)

    def get_solver_inputs(self):

        # Makes a list of dict records
        raw_sites = []
        self.input_layer = self.layers[
            self.Input_SitesLayer.currentIndex()
        ].layer()
        fieldnames = [
            field.name().lower() for field in self.input_layer.fields()
        ]
        for feature in self.input_layer.getFeatures():
            raw_sites.append(dict(zip(fieldnames, feature)))

        sites = []
        for site in raw_sites:
            s = {}
            if "latitude" in site:
                s["latitude"] = site["latitude"]
            elif "lat" in site:
                s["latitude"] = site["lat"]
            else:
                raise Exception("Requires 'latitude' or 'lat' field.")

            if "longitude" in site:
                s["longitude"] = site["longitude"]
            elif "lon" in site:
                s["longitude"] = site["lon"]
            elif "long" in site:
                s["longitude"] = site["long"]
            else:
                raise Exception("Requires 'longitude', 'lon', or 'long' field.")

            if "cost" in site:
                s["cost"] = site["cost"]

            sites.append(s)

        max_stops_per_day = self.Input_MaxSitesPerDay.value()
        bing_api_key = self.Input_BingMapsApiKey.text().strip()
        annealing_iters = 10000

        return (sites, max_stops_per_day, annealing_iters, bing_api_key)

    def create_output_layer(self, schedule_data):

        # Create a new layer and put the data into it
        name = self.Input_OutputLayerName.text() + f"_{int(time.time())}"
        output_layer = QgsVectorLayer(
            "Point",
            name,
            "memory",
        )
        pr = output_layer.dataProvider()

        # Fields
        fields = self.input_layer.fields()
        pr.addAttributes(fields)
        pr.addAttributes(
            [
                QgsField("day", QVariant.Int),
                QgsField("stop", QVariant.Int),
                QgsField("label", QVariant.String),
            ]
        )

        # tell the vector layer to fetch changes from the provider
        output_layer.updateFields()

        # Features
        features = []
        day_values = set()
        for existing in self.input_layer.getFeatures():
            if existing.id() in schedule_data:
                f = QgsFeature()
                day, stop = schedule_data[existing.id()]
                label = f"Day {day}, Stop {stop}"
                f.setAttributes(existing.attributes() + [day, stop, label])
                f.setGeometry(existing.geometry())
                features.append(f)
                day_values.add(day)

        pr.addFeatures(features)
        output_layer.updateExtents()

        # Symbology (category for each day)
        colors = [
            QtGui.QColor("#cc0000"),
            QtGui.QColor("#e69138"),
            QtGui.QColor("#f1c232"),
            QtGui.QColor("#6aa84f"),
            QtGui.QColor("#3d85c6"),
            QtGui.QColor("#fcfc97"),
            QtGui.QColor("#b6056a"),
            QtGui.QColor("#a8faa4"),
            QtGui.QColor("#0d44ba"),
            QtGui.QColor("#fea8ed"),
            QtGui.QColor("#b8e0ff"),
            QtGui.QColor("#71a6b8"),
            QtGui.QColor("#ff1919"),
            QtGui.QColor("#283148"),
            QtGui.QColor("#38414f"),
        ]

        categorized_renderer = QgsCategorizedSymbolRenderer()
        categorized_renderer.setClassAttribute("day")
        for day in day_values:
            symbol = QgsSymbol.defaultSymbol(output_layer.geometryType())
            symbol.setColor(colors[(day - 1) % len(colors)])
            category = QgsRendererCategory(day, symbol, f"Day {day}")
            categorized_renderer.addCategory(category)
        output_layer.setRenderer(categorized_renderer)

        # Labels
        label_fmt = QgsTextFormat()
        label_fmt.setSize(7)
        label = QgsPalLayerSettings()
        label.fieldName = "label"
        label.enabled = True
        label.setFormat(label_fmt)
        label.placement = QgsPalLayerSettings.Line
        labeler = QgsVectorLayerSimpleLabeling(label)
        output_layer.setLabelsEnabled(True)
        output_layer.setLabeling(labeler)

        # Add the layer to the project
        QgsProject.instance().addMapLayer(output_layer)


class SolverTask(QgsTask):
    def __init__(self, sites, max_stops_per_day, annealing_iters, bing_api_key):
        super().__init__("Solve optimization problem.", QgsTask.CanCancel)
        self.total = 0
        self.exception = None
        self.solution = None
        self.sites = sites
        self.bing_api_key = bing_api_key
        self.parameters = {
            "max_stops_per_day": max_stops_per_day,
            "annealing_iters": annealing_iters,
        }

    def run(self):
        """Run the optimization solver"""
        QgsMessageLog.logMessage(
            'Started task "{}"'.format(self.description()),
            MESSAGE_CATEGORY,
            Qgis.Info,
        )

        try:

            # Import this here so it's not attempted before depedencies
            # can be installed.
            import numpy as np

            from .solver import solve

            C_node = np.array([s.get("cost", 0) for s in self.sites])
            C_edge = get_bing_maps_edge_costs(
                self.sites, "driving", "time", self.bing_api_key
            )

            def callback(i, *args, **kwargs):
                self.setProgress(
                    int((i / self.parameters["annealing_iters"]) * 100)
                )
                if self.isCanceled():
                    return False  # Exit solver loop
                return True  # Keep running solver

            # Run the solver loop
            state, _ = solve(
                sites=self.sites,
                C_node=C_node,
                C_edge=C_edge,
                parameters=self.parameters,
                post_iteration_callback=callback,
            )

            # Coerce the state into a more convenient structure
            self.solution = {}
            day_i = 0
            for day_order in state:
                site_indices = day_order[day_order > 0]
                if len(site_indices):
                    for stop_i, site_index in enumerate(site_indices):
                        self.solution[site_index + 1] = [day_i + 1, stop_i + 1]
                    day_i += 1

            return True
        except Exception as ex:
            self.exception = ex
            return False

    def finished(self, success):
        """
        This function is automatically called when the task has
        completed (successfully or not).
        You implement finished() to do whatever follow-up stuff
        should happen after the task is complete.
        finished is always called from the main thread, so it's safe
        to do GUI operations and raise Python exceptions here.
        result is the return value from self.run.
        """
        self.success = success
        if success:
            QgsMessageLog.logMessage(
                "Solver completed",
                MESSAGE_CATEGORY,
                Qgis.Success,
            )
        else:
            if self.exception is None:
                QgsMessageLog.logMessage(
                    "Solver not successful but without "
                    "exception (probably the task was manually "
                    "canceled by the user)",
                    MESSAGE_CATEGORY,
                    Qgis.Warning,
                )
            else:
                QgsMessageLog.logMessage(
                    "Solver error. Exception: {}".format(self.exception),
                    MESSAGE_CATEGORY,
                    Qgis.Critical,
                )
                raise self.exception

    def cancel(self):
        QgsMessageLog.logMessage(
            "Solver was canceled",
            MESSAGE_CATEGORY,
            Qgis.Info,
        )
        super().cancel()


def get_bing_maps_edge_costs(
    sites,
    travel_mode,
    cost_type,
    api_key,
    start_time=None,
    force=False,
):
    """Implementation of BING Maps request using QGIS network tooling."""
    import numpy as np

    # Build and make request

    payload = {
        "travelMode": travel_mode,
        "origins": sites,
        "destinations": sites,
    }

    if start_time is not None:
        payload["startTime"] = start_time.isoformat()

    payload_bytes = json.dumps(payload).encode()

    # Caching saves us from making the same requests
    # over and over during testing and development.
    cache_key = _cache_key(payload_bytes)
    data = _read_cache(cache_key) if not force else None

    if data is None:
        QgsMessageLog.logMessage(
            "No cached data found, making request to BING...",
            MESSAGE_CATEGORY,
            Qgis.Info,
        )
        query = QUrlQuery()
        query.addQueryItem("key", api_key)
        url = QUrl("https://dev.virtualearth.net/REST/v1/Routes/DistanceMatrix")
        url.setQuery(query)
        request = QNetworkRequest(url)
        request.setHeader(QNetworkRequest.UserAgentHeader, "PyQGIS@GIS-OPS.com")
        nam = QgsNetworkAccessManager()
        response = nam.blockingPost(request, payload_bytes, forceRefresh=force)
        status_code = response.attribute(
            QNetworkRequest.HttpStatusCodeAttribute
        )

        if status_code != 200:
            raise Exception(
                f"BING Maps API request failed. Status code: {status_code}"
            )

        QgsMessageLog.logMessage(
            "Cost matrix acquired from BING",
            MESSAGE_CATEGORY,
            Qgis.Success,
        )

        data = json.loads(bytes(response.content()))
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


def _cache_key(d: bytes) -> str:
    return hashlib.md5(d).hexdigest()


def _write_cache(key: str, data_dict: dict):
    if not CACHE_DIR.exists():
        CACHE_DIR.mkdir()
    cache_file = CACHE_DIR / f"{key}.json"
    cache_file.write_text(json.dumps(data_dict))
    QgsMessageLog.logMessage(
        f"Cache write. key='{key}'",
        MESSAGE_CATEGORY,
        Qgis.Info,
    )


def _read_cache(key: str) -> dict:
    cache_file = CACHE_DIR / f"{key}.json"
    if cache_file.exists():
        data_dict = json.loads(cache_file.read_text())
        QgsMessageLog.logMessage(
            f"Cache read. key='{key}'",
            MESSAGE_CATEGORY,
            Qgis.Info,
        )
        return data_dict
    return None
