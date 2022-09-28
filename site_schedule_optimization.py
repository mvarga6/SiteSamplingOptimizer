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

import os
import sys

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QCoreApplication, QSettings, QTranslator
from qgis.PyQt.QtGui import QIcon

from .dependency_installation_dialog import (
    DEPENDENCIES_VERSION,
    DEPENDENCIES_VERSION_FILE,
)

# Initialize Qt resources from file resources.py

MESSAGE_CATEGORY = "SiteScheduleOptimization"


class SiteScheduleOptimization:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface = iface
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        self.deps_dir = os.path.join(self.plugin_dir, "dependencies")
        if self.deps_dir not in sys.path:
            sys.path.insert(0, self.deps_dir)

        # initialize locale
        locale = QSettings().value("locale/userLocale")[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            "i18n",
            "SiteScheduleOptimization_{}.qm".format(locale),
        )

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

        # Declare instance attributes
        self.actions = []
        self.menu = self.tr("&Site Schedule Optimization")

        # Check if plugin was started the first time in current QGIS session
        # Must be set in initGui() to survive plugin reloads
        self.first_start = None

    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate("SiteScheduleOptimization", message)

    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None,
    ):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        icon = QIcon(icon_path)
        action = QtWidgets.QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            # Adds plugin icon to Plugins toolbar
            self.iface.addToolBarIcon(action)

        if add_to_menu:
            self.iface.addPluginToVectorMenu(self.menu, action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        icon_path = os.path.join(self.plugin_dir, "icon.png")
        self.add_action(
            icon_path,
            text=self.tr("Generate Optimized Schedule"),
            callback=self.run,
            parent=self.iface.mainWindow(),
        )

        # will be set False in run()
        self.first_start = True

    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        for action in self.actions:
            self.iface.removePluginVectorMenu(
                self.tr("&Site Schedule Optimization"), action
            )
            self.iface.removeToolBarIcon(action)

    def run(self):
        """Run method that performs all the real work"""

        self.disableGuiActions()

        valid_dependencies = self.test_dependencies()

        # TODO: enable installation of packages directly with plugin
        # Check if we need to launch the dependency installation workflow
        # valid_dependencies = self.valid_dependencies()
        # if not valid_dependencies:
        #     self.install_dlg = DependencyInstallationDialog(self.iface)
        #     self.install_dlg.show()
        #     self.install_dlg.exec_()
        #     valid_dependencies = self.install_dlg.success
        # else:
        #     QgsMessageLog.logMessage(
        #         "Up-to-date dependencies found.",
        #         MESSAGE_CATEGORY,
        #         level=Qgis.Info,
        #     )

        if valid_dependencies:
            # Create the dialog with elements (after translation) and keep
            # reference Only create GUI ONCE in callback, so that it will
            # only load when the plugin is started
            if self.first_start:
                self.first_start = False
                from .site_schedule_optimization_dialog import (
                    SiteScheduleOptimizationDialog,
                )

                self.dlg = SiteScheduleOptimizationDialog()

            self.dlg.reset()
            self.dlg.show()
            result = self.dlg.exec_()
            if result:
                # Do something useful here - delete the line containing pass and
                # substitute with your code.
                pass

        else:
            msg = (
                "One or more python dependencies were not found. "
                + f"Check {MESSAGE_CATEGORY} logs."
            )
            QgsMessageLog.logMessage(msg, MESSAGE_CATEGORY, level=Qgis.Critical)
            self.iface.messageBar().pushMessage(
                "Error", msg, level=Qgis.Critical
            )

        self.enableGuiActions()

    def test_dependencies(self):
        """Tests if required packages can be imported."""
        success = True
        try:
            import numpy

            QgsMessageLog.logMessage(
                f"Numpy {numpy.__version__} found.",
                MESSAGE_CATEGORY,
                level=Qgis.Info,
            )
        except ModuleNotFoundError:
            success = False
            msg = "Numpy package not found. Please install."
            QgsMessageLog.logMessage(msg, MESSAGE_CATEGORY, level=Qgis.Critical)

        return success

    def valid_dependencies(self):
        """Checks whether or not valid valid python module
        dependencies are installed.

        NOTE: Not currently utilized.
        """
        self.plugin_dir = os.path.dirname(__file__)
        deps_version_file = os.path.join(
            self.deps_dir, DEPENDENCIES_VERSION_FILE
        )

        if not os.path.exists(self.deps_dir) or not os.path.exists(
            deps_version_file
        ):
            return False

        with open(deps_version_file, "r") as f:
            deps_version = int(f.read())
            if deps_version < DEPENDENCIES_VERSION:
                return False

        return True

    def disableGuiActions(self):
        for action in self.actions:
            action.setEnabled(False)

    def enableGuiActions(self):
        for action in self.actions:
            action.setEnabled(True)
