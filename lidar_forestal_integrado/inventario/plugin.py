from pathlib import Path
import os
import threading
import webbrowser
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (QAction,QDialog,QVBoxLayout,QFormLayout,QLineEdit,
    QDoubleSpinBox,QSpinBox,QPushButton,QFileDialog,QProgressBar,QPlainTextEdit,QMessageBox,QHBoxLayout,QLabel,QCheckBox,QTextBrowser)
from qgis.core import QgsApplication,QgsTask,QgsVectorLayer,QgsProject,QgsMapLayerProxyModel
from qgis.gui import QgsMapLayerComboBox,QgsFieldComboBox
from ..lidar_core.core import CATALOG, VERSION, validate
from ..lidar_core.qgis_io import read_plot_centers
from .engine import Engine
from ..lidar_core.local_work import deliver_results
from ..lidar_core.browser import default_download_directory


class Job(QgsTask):
    status = pyqtSignal(float,str)
    completed = pyqtSignal(str,str)

    def __init__(self, config, plots):
        super().__init__('LiDAR integrado · Inventario',QgsTask.CanCancel)
        self.retry_authorization = threading.Event()
        self.pause_requested = threading.Event()
        self.engine = Engine(config,plots,self.isCanceled,self.report,self.retry_authorization,self.pause_requested)
        self.message = ''
        self.result_dir = ''
        self.config=config

    def report(self,n,text):
        self.setProgress(n)
        self.status.emit(n,text)

    def run(self):
        try:
            self.result_dir = self.engine.execute()
            if self.config.get('final_destination'):
                try:
                    target=deliver_results(self.result_dir,self.config['final_destination'],self.engine.check,self.report)
                    self.report(100,'Copia final verificada: '+str(target))
                except Exception as error:
                    raise RuntimeError('El inventario local está completado en '+self.result_dir+'. La copia final falló: '+str(error)) from error
            return True
        except Exception as e:
            self.message = str(e)
            backup=getattr(self.engine,'local_diagnostic_path',None)
            if backup and str(backup) not in self.message:
                self.message+='\nDiagnóstico alternativo: '+str(backup)
            alternate_log=getattr(self.engine,'local_log_path',None)
            if alternate_log:self.message+='\nRegistro alternativo: '+str(alternate_log)
            self.result_dir = str(getattr(self.engine,'run',''))
            return False

    def finished(self,success):
        self.completed.emit(self.result_dir,self.message)


class Dialog(QDialog):
    def __init__(self,iface):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.job = None
        self._help_dialog = None
        self.setWindowTitle('Inventario de parcelas')
        self.resize(700,600)
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel('Inventario de parcelas · Windows · FUSION 4.61 · PNOA tercera cobertura'))
        form = QFormLayout()
        self.layer = QgsMapLayerComboBox()
        self.layer.setFilters(QgsMapLayerProxyModel.PointLayer)
        self.field = QgsFieldComboBox()
        self.layer.layerChanged.connect(self.field.setLayer)
        self.field.setLayer(self.layer.currentLayer())
        self.split_multipoints = QCheckBox('Separar multipuntos con varios centros')
        self.split_multipoints.setToolTip('Un MultiPoint con un centro se admite automáticamente. Con varios centros, esta opción crea IDs <ID>__p1, <ID>__p2, etc. No modifica la capa original.')
        self.radius = QDoubleSpinBox()
        self.radius.setRange(.01,10000)
        self.radius.setValue(15)
        self.radius.setSuffix(' m')
        self.cell = QDoubleSpinBox()
        self.cell.setRange(.1,20)
        self.cell.setValue(1)
        self.filter_height = QCheckBox('Aplicar altura de corte a las métricas')
        self.filter_height.setChecked(True)
        self.height_cutoff = QDoubleSpinBox()
        self.height_cutoff.setDecimals(2)
        self.height_cutoff.setRange(0,10000)
        self.height_cutoff.setValue(2)
        self.height_cutoff.setSuffix(' m')
        self.height_cutoff.setToolTip('Sólo retornos con altura normalizada superior al corte. No filtra el MDT ni modifica los LAS originales.')
        self.filter_height.toggled.connect(self.height_cutoff.setEnabled)
        self.output = QLineEdit()
        self.final_output = QLineEdit()
        self.download_directory = QLineEdit(str(default_download_directory()))
        self.download_directory.setToolTip("Carpeta donde Chrome guarda los archivos. Si usa otra, selecciónela aquí; se permiten espacios.")
        self.batch_download = QCheckBox('Descarga por lotes asistida (selección en la cesta CNIG)')
        self.batch_download.setChecked(True)
        self.batch_download.setToolTip('El complemento prepara la lista; añada sus hojas a la cesta e inicie la descarga en Chrome. Recibe los LAZ en cualquier orden.')
        self.batch_limit = QSpinBox()
        self.batch_limit.setRange(1,20)
        self.batch_limit.setValue(20)
        self.batch_download.toggled.connect(self.batch_limit.setEnabled)
        self.assume_crs = QCheckBox('Asumir CRS de parcelas sólo en archivos sin CRS (lo he comprobado)')
        self.support = QDoubleSpinBox()
        self.support.setRange(.5,20)
        self.support.setValue(5)
        self.support.setSuffix(' m')
        self.fusion = QLineEdit('C:\\FUSION')
        form.addRow('Centros de parcelas',self.layer)
        form.addRow('ID único (se conserva como texto)',self.field)
        form.addRow('',self.split_multipoints)
        form.addRow('Radio',self.radius)
        form.addRow('Celda MDT (m)',self.cell)
        form.addRow('',self.filter_height)
        form.addRow('Altura de corte (retornos >)',self.height_cutoff)
        self.coverage_hint = QLabel('FCC: primeros retornos >2 m / primeros retornos totales, siempre antes del filtro.')
        self.coverage_hint.setWordWrap(True)
        form.addRow('',self.coverage_hint)
        form.addRow('Procesamiento local (sin espacios)',self.path_row(self.output,False))
        form.addRow('Descargas de Chrome',self.path_row(self.download_directory,False))
        form.addRow('',self.batch_download)
        form.addRow('Máximo de hojas por lote',self.batch_limit)
        form.addRow('',self.assume_crs)
        form.addRow('Distancia máxima sin apoyo',self.support)
        form.addRow('FUSION',self.fusion)
        outer.addLayout(form)
        outer.addWidget(QLabel('PNOA3 desde las parcelas: consulta CNIG → Chrome normal → LAZ → LAS → FUSION.\nEn modo lotes, siga la guía para añadir hasta 20 hojas a la cesta e iniciar la descarga.\nGuarde en la carpeta indicada: el plugin detecta el archivo completo y continúa solo.'))
        buttons = QHBoxLayout()
        self.help_button = QPushButton('Ayuda')
        self.help_button.clicked.connect(self.show_help)
        self.catalog = QPushButton('Portal CNIG')
        self.catalog.clicked.connect(lambda:webbrowser.open(CATALOG))
        self.start = QPushButton('Ejecutar / reanudar')
        self.start.clicked.connect(self.execute)
        self.cancel_button = QPushButton('Cancelar')
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        self.pause_button = QPushButton('Pausar')
        self.pause_button.setEnabled(False)
        self.pause_button.setToolTip('FUSION termina el comando activo antes de pausar. Chrome continúa sus descargas.')
        self.pause_button.clicked.connect(self.toggle_pause)
        self.auth_button = QPushButton('Volver a abrir ficha')
        self.auth_button.setEnabled(False)
        self.auth_button.clicked.connect(self.continue_authorization)
        for button in (self.help_button,self.catalog,self.start,self.pause_button,self.auth_button,self.cancel_button):
            buttons.addWidget(button)
        outer.addLayout(buttons)
        self.bar = QProgressBar()
        outer.addWidget(self.bar)
        self.messages = QPlainTextEdit()
        self.messages.setReadOnly(True)
        outer.addWidget(self.messages)

    def show_help(self):
        if self._help_dialog is None:
            self._help_dialog = QDialog(self)
            self._help_dialog.setWindowTitle('Ayuda · Inventario forestal LiDAR')
            self._help_dialog.resize(760,650)
            layout = QVBoxLayout(self._help_dialog)
            self.help_browser = QTextBrowser()
            self.help_browser.setOpenExternalLinks(True)
            self.help_browser.setHtml((Path(__file__).parent/'docs'/'AYUDA.html').read_text(encoding='utf-8'))
            layout.addWidget(self.help_browser)
            close = QPushButton('Cerrar ayuda')
            close.clicked.connect(self._help_dialog.close)
            layout.addWidget(close)
        self._help_dialog.show()
        self._help_dialog.raise_()

    def toggle_pause(self):
        if not self.job or self.job.isCanceled():
            return
        if self.job.pause_requested.is_set():
            self.job.pause_requested.clear()
            self.pause_button.setText('Pausar')
            self.messages.appendPlainText('Reanudación solicitada.')
        else:
            self.job.pause_requested.set()
            self.pause_button.setText('Retirar pausa')
            self.messages.appendPlainText('Pausa solicitada: se aplicará en el próximo punto seguro. FUSION terminará el comando activo; Chrome continúa sus descargas.')

    def continue_authorization(self):
        if self.job:
            self.job.retry_authorization.set()
            self.messages.appendPlainText('Se solicita volver a abrir la guía del lote o ficha CNIG en Chrome normal.')

    def path_row(self,edit,file):
        from qgis.PyQt.QtWidgets import QWidget
        box = QWidget()
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0,0,0,0)
        layout.addWidget(edit)
        button = QPushButton('…')
        def choose():
            path = QFileDialog.getOpenFileName(self,'Índice CNIG','','CSV (*.csv)')[0] if file else QFileDialog.getExistingDirectory(self,'Carpeta de trabajo')
            if path:
                edit.setText(path)
        button.clicked.connect(choose)
        layout.addWidget(button)
        return box

    def execute(self):
        try:
            if os.name != 'nt':
                raise ValueError('El procesamiento FUSION requiere Windows')
            layer = self.layer.currentLayer()
            field = self.field.currentField()
            if not layer or not layer.isValid() or field not in layer.fields().names():
                raise ValueError('Seleccione capa de puntos y campo ID')
            if layer.crs().authid() not in ('EPSG:25828','EPSG:25829','EPSG:25830','EPSG:25831','EPSG:4083'):
                raise ValueError('Reproyecte la capa al CRS UTM de las teselas (ETRS89 o REGCAN95)')
            plots, origins = read_plot_centers(layer,field,self.split_multipoints.isChecked())
            output = self.output.text().strip()
            if not output or not Path(output).is_absolute():
                raise ValueError('Seleccione una carpeta absoluta de trabajo')
            downloads = self.download_directory.text().strip()
            if not downloads or not Path(downloads).is_absolute():
                raise ValueError('Indique la carpeta absoluta donde Chrome guarda las descargas')
            validate(plots,self.radius.value(),output)
            config = {'final_destination':self.final_output.text().strip(),'output':output,'download_directory':downloads,'assume_missing_crs':self.assume_crs.isChecked(),
                      'batch_download':self.batch_download.isChecked(),'batch_limit':self.batch_limit.value(),
                      'height_cutoff':self.height_cutoff.value() if self.filter_height.isChecked() else None,
                      'support_distance':self.support.value(),'fusion':self.fusion.text(),
                      'epsg':int(layer.crs().authid().split(':')[1]),'radius':self.radius.value(),'cell':self.cell.value()}
            config['input_centers'] = origins
            config['split_multipoints'] = self.split_multipoints.isChecked()
            self.job = Job(config,plots)
            self.job.status.connect(self.status)
            self.job.completed.connect(self.finished)
            self.start.setEnabled(False)
            self.cancel_button.setEnabled(True)
            self.auth_button.setText('Volver a abrir lote' if config['batch_download'] else 'Volver a abrir ficha')
            self.pause_button.setText('Pausar')
            self.pause_button.setEnabled(True)
            self.messages.appendPlainText('Inicio. Se procesan todas las entidades de la capa: '+str(len(plots))+' centros. Correspondencia de ID en parcelas_entrada.json.')
            QgsApplication.taskManager().addTask(self.job)
        except Exception as e:
            QMessageBox.warning(self,'Validación',str(e))

    def status(self,n,text):
        self.bar.setValue(int(n))
        self.messages.appendPlainText(text)
        if self.job and self.job.pause_requested.is_set() and text.startswith('En pausa.'):
            self.pause_button.setText('Reanudar')
        self.auth_button.setEnabled(self.job is not None and (text.startswith('CNIG autorización:') or text.startswith('CNIG vigilando:') or text.startswith('CNIG archivo completo incorporado:')))

    def cancel(self):
        if self.job:
            self.job.cancel()
            self.pause_button.setEnabled(False)
            self.messages.appendPlainText('Cancelación solicitada; se detendrá el proceso activo. Chrome y sus descargas permanecen abiertos.')

    def finished(self,path,message):
        self.start.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.pause_button.setText('Pausar')
        self.auth_button.setEnabled(False)
        self.messages.appendPlainText((('ERROR · '+message) if message else 'Completado: CloudMetrics y CSV/GeoPackage exportados')+'\nResultados y registro: '+path)
        self.job = None
        if not message:
            layer = QgsVectorLayer(str(Path(path)/'metricas.gpkg'),'Inventario LiDAR','ogr')
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)

    def closeEvent(self,event):
        if self.job:
            self.cancel()
            event.ignore()
        else:
            event.accept()

    def reject(self):
        if self.job:
            self.cancel()
        else:
            super().reject()


class Plugin:
    def __init__(self,iface):
        self.iface = iface
        self.dialog = None

    def initGui(self):
        self.action = QAction('Inventario forestal LiDAR',self.iface.mainWindow())
        self.action.triggered.connect(self.open)
        self.iface.addPluginToMenu('Inventario forestal LiDAR',self.action)
        self.iface.addToolBarIcon(self.action)

    def open(self):
        if self.dialog is None:
            self.dialog = Dialog(self.iface)
        self.dialog.show()
        self.dialog.raise_()

    def unload(self):
        if self.dialog and self.dialog.job:
            self.dialog.job.cancel()
        self.iface.removePluginMenu('Inventario forestal LiDAR',self.action)
        self.iface.removeToolBarIcon(self.action)
