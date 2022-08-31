# -*- coding: utf-8 -*-
"""
/***************************************************************************
 DependencyInstallationDialog

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

import os
import subprocess

from qgis.core import Qgis, QgsApplication, QgsMessageLog, QgsTask
from qgis.PyQt import QtWidgets, uic


FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "dependency_installation_dialog.ui")
)

DEPENDENCIES_VERSION = 1
DEPENDENCIES_VERSION_FILE = "deps_version"
MESSAGE_CATEGORY = "SiteScheduleOptimization"


class DependencyInstallationDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, iface, parent=None):
        """Constructor."""
        super(DependencyInstallationDialog, self).__init__(parent)
        self.setupUi(self)

        self.plugin_dir = os.path.dirname(__file__)
        self.deps_dir = os.path.join(self.plugin_dir, "dependencies")
        self.success = False
        self.iface = iface

        self.progressBar.setValue(0)
        self.progressBar.hide()
        self.installingLabel.hide()
        self.installButton.clicked.connect(self.run)
        self.cancelButton.clicked.connect(self._on_cancel)

    def set_success(self, x):
        self.success = x

    def run(self):
        self.installButton.hide()
        self.progressBar.show()
        self.installingLabel.show()

        QgsMessageLog.logMessage(
            "Running installation", MESSAGE_CATEGORY, level=Qgis.Info
        )
        self.iface.messageBar().pushMessage(
            "Info", "Running installation", level=Qgis.Info
        )

        try:
            import pip

            QgsMessageLog.logMessage(
                f"Pip {pip.__version__} found.",
                MESSAGE_CATEGORY,
                level=Qgis.Info,
            )
        except ModuleNotFoundError:
            msg = """
            Pip (Package Installer for Python) is not installed on your
            computer. It is required for the Site Schedule Optimization
            plugin to install its required dependencies.

            Please install, restart QGIS, then try again.
            https://pip.pypa.io/en/stable/installation/
            """
            self.iface.messageBar().pushMessage(
                "Error", msg, level=Qgis.Critical
            )
            QgsMessageLog.logMessage(msg, MESSAGE_CATEGORY, level=Qgis.Critical)
            self.close()
            return

        requirements_file = os.path.join(
            self.plugin_dir, "requirements.qgis.txt"
        )
        self.task = InstallDependenciesTask(requirements_file, self.deps_dir)
        self.task.progressChanged.connect(
            lambda x: self.progressBar.setValue(x)
        )
        self.task.taskCompleted.connect(self._on_task_completed)
        QgsApplication.taskManager().addTask(self.task)

    def _on_cancel(self):
        if self.task is not None:
            self.task.cancel()
        self.close()

    def _on_task_completed(self):
        self.set_success(self.task.success)
        self.close()


class InstallDependenciesTask(QgsTask):
    def __init__(self, requirements_file, install_dir):
        super().__init__(
            "Install required Python packages for Site Schedule Optimization",
            QgsTask.CanCancel,
        )
        self.requirements_file = requirements_file
        self.install_dir = install_dir
        self.success = False

    def run(self):
        """"""
        QgsMessageLog.logMessage(
            f"Installing dependencies task started in {os.getcwd()}...",
            MESSAGE_CATEGORY,
            Qgis.Info,
        )
        self.setProgress(0)

        if not os.path.exists(self.install_dir):
            os.makedirs(self.install_dir)

        installation_success = []
        requirements = list(open(self.requirements_file).readlines())
        for i, requirement in enumerate(requirements):
            QgsMessageLog.logMessage(
                f"Installing '{requirement.strip()}' to '{self.install_dir}'",
                MESSAGE_CATEGORY,
                level=Qgis.Info,
            )

            proc = subprocess.run(
                [
                    "pip",
                    "install",
                    "--upgrade",
                    f"--target={self.install_dir}",
                    requirement.strip(),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            QgsMessageLog.logMessage(
                proc.stdout, MESSAGE_CATEGORY, level=Qgis.Info
            )
            installation_success.append(proc.returncode == 0)

            self.setProgress(int((i + 1) / len(requirements) * 100))
            if self.isCanceled():
                return False

        QgsMessageLog.logMessage(
            "=====================", MESSAGE_CATEGORY, level=Qgis.Info
        )
        QgsMessageLog.logMessage(
            "INSTALLLATION RESULTS", MESSAGE_CATEGORY, level=Qgis.Info
        )
        QgsMessageLog.logMessage(
            "=====================", MESSAGE_CATEGORY, level=Qgis.Info
        )
        for requirement, success in zip(requirements, installation_success):
            level = Qgis.Success if success else Qgis.Warning
            QgsMessageLog.logMessage(
                requirement.strip(), MESSAGE_CATEGORY, level=level
            )

        return True

    def finished(self, success):
        """
        - Enable the button to use the plugin.
        - Report to use the plugin is usable.
        """
        self.success = success
        if success:
            QgsMessageLog.logMessage(
                "Dependency installation completed.",
                MESSAGE_CATEGORY,
                Qgis.Success,
            )
            deps_version_file = os.path.join(
                self.install_dir, DEPENDENCIES_VERSION_FILE
            )
            with open(deps_version_file, "w") as f:
                f.write(str(DEPENDENCIES_VERSION))
        else:
            QgsMessageLog.logMessage(
                "Dependency installation failed.",
                MESSAGE_CATEGORY,
                Qgis.Critical,
            )

    def cancel(self):
        QgsMessageLog.logMessage(
            "Dependency installation will terminate after current package.",
            MESSAGE_CATEGORY,
            Qgis.Info,
        )
        super().cancel()
