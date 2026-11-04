"""One QGIS entry point, three independent modules and explicit output hand-offs."""
from pathlib import Path
import json

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (QAction,QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,
    QLabel,QLineEdit,QPushButton,QFileDialog,QTabWidget,QScrollArea,QWidget,QMessageBox)

from .inventario.plugin import Dialog as InventoryDialog
from .cartografia.plugin import Dialog as CartographyDialog
from .modelizacion.plugin import Dialog as ModelDialog, dependencies
from .contracts import metric_protocol
from .lidar_core.local_work import local_workspace


class InventoryPanel(InventoryDialog):
    def __init__(self,iface,hub):
        self.hub=hub
        super().__init__(iface)
    def execute(self):
        if self.hub.can_start():
            super().execute()
            self.hub.refresh()
    def finished(self,path,error):
        super().finished(path,error)
        self.hub.record_inventory(path)
        self.hub.refresh()
    def reject(self):
        if self.job:self.cancel()


class ModelPanel(ModelDialog):
    def __init__(self,parent,hub):
        self.hub=hub
        super().__init__(parent)
    def execute(self):
        if not self.hub.can_start():return
        try:
            if self.output.text().strip():local_workspace(self.output.text().strip())
        except ValueError as error:
            QMessageBox.warning(self,'Procesamiento local',str(error));return
        super().execute()
        self.hub.refresh()
    def done_task(self,success,error):
        super().done_task(success,error)
        if success and self.result_path:
            self.hub.record_models(self.result_path)
        self.hub.refresh()
    def reject(self):
        if self.task:self.cancel_task()


class CartographyPanel(CartographyDialog):
    def __init__(self,iface,hub):
        self.hub=hub
        super().__init__(iface)
    def execute(self):
        if self.hub.can_start():
            super().execute()
            self.hub.refresh()
    def copy_results(self):
        if self.hub.can_start():
            super().copy_results()
            self.hub.refresh()
    def finished(self,path,error):
        super().finished(path,error)
        self.hub.refresh()
    def reject(self):
        if self.job:self.cancel()


class Dialog(QDialog):
    def __init__(self,iface):
        super().__init__(iface.mainWindow())
        self.iface=iface
        self.latest_metrics=None
        self.latest_models=None
        self.inventory=self.cartography=self.model=None
        self.setWindowTitle('LiDAR forestal integrado · Experimental 0.1.1')
        self.resize(1100,950)
        layout=QVBoxLayout(self)
        title=QLabel('Inventario de parcelas → Modelización → Cartografía DasoLiDAR de 20 × 20 m')
        title.setWordWrap(True);layout.addWidget(title)
        self.banner=QLabel('Cada módulo puede usarse por separado. Sólo se ejecuta una tarea de la suite a la vez.')
        self.banner.setWordWrap(True);layout.addWidget(self.banner)
        shared=QFormLayout()
        self.work=QLineEdit();self.fusion=QLineEdit('C:\\FUSION')
        self.downloads=QLineEdit();self.final=QLineEdit()
        for label,edit in [('Procesamiento local (sin espacios)',self.work),('FUSION',self.fusion),
                           ('Descargas de Chrome',self.downloads),('Destino final opcional (admite red)',self.final)]:
            row=QHBoxLayout();row.addWidget(edit)
            button=QPushButton('…')
            button.clicked.connect(lambda checked=False,e=edit:self.choose_directory(e))
            row.addWidget(button);shared.addRow(label,row)
        self.shared_widget=QWidget();self.shared_widget.setLayout(shared)
        layout.addWidget(self.shared_widget)
        self.tabs=QTabWidget();layout.addWidget(self.tabs,1)
        self.inventory=InventoryPanel(iface,self)
        self.cartography=CartographyPanel(iface,self)
        self.add_panel(self.inventory,'1 · Inventario')
        self.model_placeholder=QWidget()
        self.tabs.addTab(self.model_placeholder,'2 · Modelización')
        self.add_panel(self.cartography,'3 · Cartografía DasoLiDAR')
        self.initialize_model()
        self.downloads.setText(self.inventory.download_directory.text())
        for common,widgets in [(self.work,[self.inventory.output,self.cartography.output]),
                               (self.fusion,[self.inventory.fusion,self.cartography.fusion]),
                               (self.downloads,[self.inventory.download_directory,self.cartography.downloads]),
                               (self.final,[self.inventory.final_output,self.cartography.final_output])]:
            for edit in widgets:
                edit.setText(common.text())
                common.textChanged.connect(lambda text,e=edit:e.setText(text) if e.text()!=text else None)
                edit.textChanged.connect(lambda text,c=common:c.setText(text) if c.text()!=text else None)
                self.hide_shared_row(edit)
        buttons=QHBoxLayout()
        self.to_model=QPushButton('Métricas → Modelización')
        self.to_model.clicked.connect(self.transfer_metrics)
        self.to_map=QPushButton('Modelos → Cartografía')
        self.to_map.clicked.connect(self.transfer_models)
        self.help_button=QPushButton('Ayuda general')
        self.help_button.clicked.connect(self.show_help)
        for button in (self.to_model,self.to_map,self.help_button):buttons.addWidget(button)
        layout.addLayout(buttons)
        self.refresh()
        self.refresh_timer=QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start(500)

    def add_panel(self,panel,title,index=None):
        panel.setWindowFlags(Qt.Widget)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(panel)
        if index is None:self.tabs.addTab(scroll,title)
        else:self.tabs.insertTab(index,scroll,title)

    def hide_shared_row(self,edit):
        for panel in (self.inventory,self.cartography):
            for form in panel.findChildren(QFormLayout):
                for candidate in (edit,edit.parentWidget()):
                    if candidate is not None and form.labelForField(candidate) is not None:
                        form.labelForField(candidate).hide()
                        candidate.hide()
                        return

    def initialize_model(self):
        errors=dependencies()
        if errors:
            layout=self.model_placeholder.layout() or QVBoxLayout(self.model_placeholder)
            notice=QLabel('Modelización necesita NumPy, pandas y matplotlib en el Python de QGIS.\n'+ '\n'.join(errors)+'\nInventario y cartografía siguen disponibles. Solicite una instalación autorizada de estas dependencias; el complemento no instala paquetes.')
            notice.setWordWrap(True);layout.addWidget(notice)
            retry=QPushButton('Recomprobar dependencias')
            retry.clicked.connect(self.initialize_model);layout.addWidget(retry)
            return
        if self.model is not None:return
        self.model=ModelPanel(self,self)
        index=self.tabs.indexOf(self.model_placeholder)
        self.tabs.removeTab(index)
        self.add_panel(self.model,'2 · Modelización',index)
        self.refresh()

    def choose_directory(self,edit):
        path=QFileDialog.getExistingDirectory(self,'Seleccionar carpeta',edit.text())
        if path:edit.setText(path)

    def busy(self):
        own=any(getattr(panel,'job',None) is not None or getattr(panel,'task',None) is not None
                for panel in (self.inventory,self.model,self.cartography) if panel is not None)
        if own:return True
        return any(task.description().startswith('LiDAR integrado ·') and task.isActive()
                   for task in QgsApplication.taskManager().tasks())

    def can_start(self):
        if self.busy():
            QMessageBox.information(self,'Proceso activo','Espere a que termine o se cancele el proceso activo antes de ejecutar otro módulo.')
            return False
        return True

    def refresh(self):
        busy=self.busy()
        self.shared_widget.setEnabled(not busy)
        for panel in (self.inventory,self.model,self.cartography):
            if panel is not None:panel.start.setEnabled(not busy)
        if self.cartography is not None:self.cartography.copy_button.setEnabled(not busy)
        if hasattr(self,'to_model'):
            self.to_model.setEnabled(not busy and self.model is not None)
            self.to_map.setEnabled(not busy)
            for edit in (self.work,self.fusion,self.downloads,self.final):edit.setEnabled(not busy)

    def record_inventory(self,directory):
        if not directory:return
        directory=Path(directory)
        state=directory/'estado.json'
        if state.is_file() and json.loads(state.read_text(encoding='utf-8')).get('status')=='completed' and (directory/'metricas.csv').is_file():
            self.latest_metrics=directory/'metricas.csv'
            self.banner.setText('Inventario completado. Use «Métricas → Modelización» para cargar '+str(self.latest_metrics))

    def record_models(self,path):
        path=Path(path)
        file=path/'modelos.json' if path.is_dir() else path
        if file.name=='modelos.json' and file.is_file():
            self.latest_models=file
            self.banner.setText('Modelos guardados. Use «Modelos → Cartografía» para cargarlos sin copiar ecuaciones.')

    def transfer_metrics(self):
        if not self.can_start() or self.model is None:return
        path=str(self.latest_metrics) if self.latest_metrics else QFileDialog.getOpenFileName(self,'Métricas de inventario','','CSV (*.csv)')[0]
        if not path:return
        try:
            protocol=metric_protocol(path)
            self.model.lidar.setText(path)
            if not self.model.output.text().strip() and self.work.text().strip():
                from datetime import datetime
                import uuid
                self.model.output.setText(str(Path(self.work.text())/'modelos'/(datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])))
            self.model.load_columns('lidar')
            self.model.protocol.setCurrentIndex(0)  # Standard cm_ columns retain their real filter metadata.
            self.model.info.appendPlainText('Métricas recibidas de Inventario. Corte estándar: '+str(protocol['cm_standard_height_filter_m'])+' m; metadatos conocidos: '+str(protocol['known'])+'. Seleccione datos de campo, respuestas y métricas antes de ajustar.')
            self.tabs.setCurrentIndex(1)
        except Exception as error:QMessageBox.warning(self,'Métricas',str(error))

    def transfer_models(self):
        if not self.can_start():return
        path=str(self.latest_models) if self.latest_models else QFileDialog.getOpenFileName(self,'Modelos guardados','','Modelos JSON (*.json)')[0]
        if not path:return
        self.cartography.model_path.setText(path)
        self.cartography.load_model_choices()
        self.tabs.setCurrentIndex(2)

    def show_help(self):
        from qgis.PyQt.QtWidgets import QTextBrowser
        dialog=QDialog(self);dialog.setWindowTitle('Ayuda · LiDAR forestal integrado');dialog.resize(850,700)
        layout=QVBoxLayout(dialog);browser=QTextBrowser();browser.setOpenExternalLinks(True)
        browser.setHtml((Path(__file__).parent/'AYUDA.html').read_text(encoding='utf-8'));layout.addWidget(browser)
        close=QPushButton('Cerrar');close.clicked.connect(dialog.close);layout.addWidget(close)
        dialog.exec()

    def cancel_all(self):
        for panel in (self.inventory,self.cartography):
            if panel and panel.job:panel.cancel()
        if self.model and self.model.task:self.model.cancel_task()

    def closeEvent(self,event):
        if self.busy():
            self.cancel_all();self.banner.setText('Cancelación solicitada; espere a que terminen las tareas antes de cerrar.');event.ignore()
        else:
            self.refresh_timer.stop();event.accept()

    def showEvent(self,event):
        super().showEvent(event)
        self.refresh_timer.start(500)
        self.refresh()

    def reject(self):self.close()


class Plugin:
    def __init__(self,iface):self.iface=iface;self.dialog=None
    def initGui(self):
        self.action=QAction('LiDAR forestal integrado',self.iface.mainWindow())
        self.action.setIcon(QgsApplication.getThemeIcon('/mIconPolygonLayer.svg'))
        self.action.triggered.connect(self.open)
        self.iface.addPluginToMenu('LiDAR forestal integrado',self.action);self.iface.addToolBarIcon(self.action)
    def open(self):
        if self.dialog is None:self.dialog=Dialog(self.iface)
        self.dialog.show();self.dialog.raise_()
    def unload(self):
        if self.dialog:self.dialog.cancel_all();self.dialog.refresh_timer.stop();self.dialog.hide()
        self.iface.removePluginMenu('LiDAR forestal integrado',self.action);self.iface.removeToolBarIcon(self.action)
