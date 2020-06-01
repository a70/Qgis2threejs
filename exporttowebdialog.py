# -*- coding: utf-8 -*-
"""
/***************************************************************************
 ExportToWebDialog

                              -------------------
        begin                : 2017-06-11
        copyright            : (C) 2017 Minoru Akagi
        email                : akaginch@gmail.com
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
from datetime import datetime

from PyQt5.QtCore import Qt, QDir, QEventLoop, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QDialog, QFileDialog, QMessageBox
from qgis.core import Qgis, QgsApplication

from .export import ThreeJSExporter
from .qgis2threejstools import getTemplateConfig, openUrl, templateDir, temporaryOutputDir
from .ui.exporttowebdialog import Ui_ExportToWebDialog


class ExportToWebDialog(QDialog):

    def __init__(self, settings, page, parent=None):
        QDialog.__init__(self, parent)
        self.setAttribute(Qt.WA_DeleteOnClose)

        self.settings = settings
        self.page = page
        self.logHtml = ""
        self.logNextIndex = 1

        self.ui = Ui_ExportToWebDialog()
        self.ui.setupUi(self)

        # output directory
        self.ui.lineEdit_OutputDir.setText(os.path.dirname(settings.outputFileName()))

        # template combo box
        cbox = self.ui.comboBox_Template
        for i, entry in enumerate(QDir(templateDir()).entryList(["*.html", "*.htm"])):
            config = getTemplateConfig(entry)
            cbox.addItem(config.get("name", entry), entry)

            # set tool tip text
            desc = config.get("description", "")
            if desc:
                cbox.setItemData(i, desc, Qt.ToolTipRole)

        index = cbox.findData(settings.template())
        if index != -1:
            cbox.setCurrentIndex(index)

        self.templateChanged()

        # general settings
        self.ui.checkBox_PreserveViewpoint.setChecked(bool(settings.option("viewpoint")))
        self.ui.checkBox_LocalMode.setChecked(bool(settings.option("localMode")))

        # template settings
        for key, value in settings.options().items():
            if key == "AR.MND":
                self.ui.lineEdit_MND.setText(str(value))

        self.ui.comboBox_Template.currentIndexChanged.connect(self.templateChanged)
        self.ui.pushButton_Browse.clicked.connect(self.browseClicked)

        self.ui.textBrowser.setOpenLinks(False)
        self.ui.textBrowser.anchorClicked.connect(openUrl)

    def templateChanged(self, index=None):
        # update settings widget visibility
        config = getTemplateConfig(self.ui.comboBox_Template.currentData())
        optset = set(config.get("options", "").split(","))
        optset.discard("")

        for widget in [self.ui.label_MND, self.ui.lineEdit_MND, self.ui.label_MND2]:
            widget.setVisible("AR.MND" in optset)

    def browseClicked(self):
        # directory select dialog
        d = self.ui.lineEdit_OutputDir.text() or QDir.homePath()
        d = QFileDialog.getExistingDirectory(self, self.tr("Select Output Directory"), d)
        if d:
            self.ui.lineEdit_OutputDir.setText(d)

    def accept(self):
        """export"""

        self.settings.clearOptions()

        # general settings
        if self.ui.checkBox_PreserveViewpoint.isChecked():
            self.settings.setOption("viewpoint", self.page.cameraState())

        local_mode = self.ui.checkBox_LocalMode.isChecked()
        if local_mode:
            self.settings.setOption("localMode", True)

        # template settings
        self.settings.setTemplate(self.ui.comboBox_Template.currentData())

        options = self.settings.templateConfig().get("options", "")
        if options:
            optlist = options.split(",")

            if "AR.MND" in optlist:
                try:
                    self.settings.setOption("AR.MND", float(self.ui.lineEdit_MND.text()))
                except Exception as e:
                    QMessageBox.warning(self, "Qgis2threejs", "Invalid setting value for M.N. direction. Must be a numeric value.")
                    return

        # output html file name
        out_dir = self.ui.lineEdit_OutputDir.text()
        filename = self.ui.lineEdit_Filename.text()
        is_temporary = (out_dir == "")
        if is_temporary:
            out_dir = temporaryOutputDir()
            # title, ext = os.path.splitext(filename)
            # filename = title + datetime.today().strftime("%Y%m%d%H%M%S") + ext

        filepath = os.path.join(out_dir, filename)
        if not is_temporary and os.path.exists(filepath):
            if QMessageBox.question(self, "Qgis2threejs", "The HTML file already exists. Do you want to overwrite it?", QMessageBox.Ok | QMessageBox.Cancel) != QMessageBox.Ok:
                return

        if is_temporary:
            settings = self.settings.clone()
            settings.setOutputFilename(filepath)
        else:
            self.settings.setOutputFilename(filepath)
            settings = self.settings.clone()

        settings.isPreview = False
        settings.localMode = settings.base64 = local_mode

        err_msg = settings.checkValidity()
        if err_msg:
            QMessageBox.warning(self, "Qgis2threejs", err_msg or "Invalid settings")
            return

        for w in [self.ui.tabSettings, self.ui.pushButton_Export, self.ui.pushButton_Close]:
            w.setEnabled(False)

        self.ui.tabWidget.setCurrentIndex(1)

        self.logNextIndex = 1
        self.logHtml = """
<style>
div.progress {margin-top:10px;}
div.indented {margin-left:3em;}
th {text-align:left;}
</style>
"""
        self.progress(0, "Export has been started.")
        t0 = datetime.now()

        # export
        exporter = ThreeJSExporter(settings, self.progressNumbered, self.logMessageIndented)
        exporter.export()

        elapsed = datetime.now() - t0
        self.progress(100, "<br><a name='complete'>Export has been completed in {:,.2f} seconds.</a>".format(elapsed.total_seconds()))

        data_dir = settings.outputDataDirectory()

        url_dir = QUrl.fromLocalFile(out_dir)
        url_data = QUrl.fromLocalFile(data_dir)
        url_scene = QUrl.fromLocalFile(os.path.join(data_dir, "scene.js" if local_mode else "scene.json"))
        url_page = QUrl.fromLocalFile(filepath)

        self.logHtml += """
<br>
<table>
<tr><th>Output directory</th><td><a href="{}">{}</a></td></tr>
<tr><th>Data directory</th><td><a href="{}">{}</a></td></tr>
<tr><th>Scene file</th><td>{}</td></tr>
<tr><th>Web page file</th><td><a href="{}">{}</a></td></tr>
</table>
""".format(url_dir.toString(), url_dir.toLocalFile(),
           url_data.toString(), url_data.toLocalFile(),
                                url_scene.toLocalFile(),
           url_page.toString(), url_page.toLocalFile())

        self.ui.textBrowser.setHtml(self.logHtml)
        self.ui.textBrowser.scrollToAnchor("complete")

        for w in [self.ui.tabSettings, self.ui.pushButton_Export, self.ui.pushButton_Close]:
            w.setEnabled(True)

    def progress(self, percentage=None, msg=None, numbered=False):
        if percentage is not None:
            self.ui.progressBar.setValue(percentage)

            v = bool(percentage != 100)
            self.ui.progressBar.setEnabled(v)
            self.ui.pushButton_Cancel.setEnabled(v)

        if msg:
            if numbered:
                msg = "{}. {}".format(self.logNextIndex, msg)
                self.logNextIndex += 1
            self.logHtml += "<div class='progress'>{}</div>".format(msg)
            self.ui.textBrowser.setHtml(self.logHtml)

        QgsApplication.processEvents(QEventLoop.ExcludeUserInputEvents)

    def progressNumbered(self, percentage=None, msg=None):
        self.progress(percentage, msg, numbered=True)

    def logMessage(self, msg, level=Qgis.Info, indented=False):
        self.logHtml += "<div{}>{}</div>".format(" class='indented'" if indented else "", msg)
        self.ui.textBrowser.setHtml(self.logHtml)

        QgsApplication.processEvents(QEventLoop.ExcludeUserInputEvents)

    def logMessageIndented(self, msg, level=Qgis.Info):
        self.logMessage(msg, level, indented=True)
