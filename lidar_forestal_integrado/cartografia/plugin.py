from pathlib import Path
import hashlib
import os
import threading
import time

from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (QAction, QDialog, QVBoxLayout, QFormLayout, QLineEdit,
    QDoubleSpinBox, QPushButton, QFileDialog, QProgressBar, QPlainTextEdit,
    QMessageBox, QHBoxLayout, QLabel, QTextBrowser, QComboBox, QScrollArea, QWidget)
from qgis.core import QgsApplication, QgsTask, QgsVectorLayer, QgsProject, QgsMapLayerProxyModel
from qgis.gui import QgsMapLayerComboBox

from .grid import snapshot, cells
from .workflow import GridEngine
from .models import load_models, read_package, TARGETS
from ..lidar_core.browser import default_download_directory
from ..lidar_core.core import Cancelled
from .local_work import local_workspace, deliver_results


class Job(QgsTask):
    status = pyqtSignal(float, str)
    completed = pyqtSignal(str, str)

    def __init__(self, config, wkb, models=None):
        super().__init__('LiDAR integrado · Cartografía', QgsTask.CanCancel)
        self.config, self.wkb = config, wkb
        self.models = models or load_models()
        self.pause_requested = threading.Event()
        self.retry = threading.Event()
        self.engine = None
        self.directory = self.message = ''

    def report(self, n, text):
        self.setProgress(n)
        self.status.emit(n,text)

    def check(self):
        if self.isCanceled():
            raise Cancelled('Cancelado por el usuario')
        if self.pause_requested.is_set():
            self.report(0,'En pausa. Pulse «Reanudar» para continuar.')
        while self.pause_requested.is_set():
            if self.isCanceled():
                raise Cancelled('Cancelado por el usuario')
            time.sleep(.1)

    def run(self):
        try:
            if self.config.get('copy_run'):
                self.directory=self.config['copy_run']
                target=deliver_results(self.directory,self.config['final_destination'],self.check,self.report)
                self.report(100,'Copia final verificada: '+str(target))
                return True
            self.report(0,'Generando cuadrícula de 20 × 20 m…')
            grid = cells(self.wkb,self.check)
            self.check()
            self.report(0,str(len(grid))+' celdas completas de 400 m². FCC y P95 fijos; modelos guardados sin reajustar.')
            self.config['aoi_sha256'] = hashlib.sha256(self.wkb).hexdigest()
            self.engine = GridEngine(self.config,grid,self.models,self.isCanceled,self.report,self.retry,self.pause_requested)
            self.engine.aoi_wkb = self.wkb
            self.directory = self.engine.execute()
            if self.config.get('final_destination'):
                try:
                    target=deliver_results(self.directory,self.config['final_destination'],self.check,self.report)
                    self.report(100,'Copia final verificada: '+str(target))
                except Exception as error:
                    raise RuntimeError('El cálculo local está completado y conservado en '+self.directory+
                        '. La copia final no terminó: '+str(error)+'. Use «Copiar resultados locales» para reintentar sin recalcular.') from error
            return True
        except Exception as error:
            self.message = str(error)
            if self.engine is not None:
                self.directory = str(getattr(self.engine,'run',''))
                alternate = getattr(self.engine,'local_log_path',None)
                if alternate:
                    self.message += '\nRegistro alternativo: '+str(alternate)
            return False

    def finished(self, success):
        self.completed.emit(self.directory,self.message)


class Dialog(QDialog):
    def __init__(self, iface):
        super().__init__(iface.mainWindow())
        self.iface, self.job, self.help_dialog = iface, None, None
        self.setWindowTitle('Cartografía forestal LiDAR 20 m · Experimental 0.1.1')
        self.resize(900,780)
        layout = QVBoxLayout(self)
        title = QLabel('Polígono → CNIG/LAZ → LAS normalizado → celdas 20 × 20 m → SHP y GeoPackage')
        title.setWordWrap(True)
        layout.addWidget(title)
        form = QFormLayout()
        self.layer = QgsMapLayerComboBox()
        self.layer.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        form.addRow('Polígono de trabajo',self.layer)
        form.addRow('Cuadrícula fija',QLabel('20 × 20 m · cuadrados completos · alineación UTM a múltiplos de 20'))
        form.addRow('FCC fija',QLabel('Primeros retornos > 2 m / primeros retornos totales · ratio 0–1'))
        form.addRow('Altura dominante',QLabel('P95 de todos los retornos normalizados, sin filtro de altura · metros'))
        self.model_notice = QLabel('Seleccione modelos.json exportado por Modelización forestal LiDAR. Asigne sus respuestas a N/ha, volumen/ha y área basal/ha; sin modelo se exporta NULL.')
        self.model_notice.setWordWrap(True)
        form.addRow('Ecuaciones',self.model_notice)
        self.model_path = QLineEdit()
        model_box = QHBoxLayout()
        model_box.addWidget(self.model_path)
        choose_model=QPushButton('…')
        model_box.addWidget(choose_model)
        choose_model.clicked.connect(self.choose_models)
        self.model_path.editingFinished.connect(self.load_model_choices)
        form.addRow('Archivo de modelos del segundo plugin',model_box)
        self.model_targets={}
        for output,label in [('N_HA','Número de pies/ha'),('VOL_HA','Volumen m³/ha'),('AB_HA','Área basal m²/ha')]:
            combo=QComboBox()
            combo.addItem('(sin modelo)',None)
            self.model_targets[output]=combo
            form.addRow(label,combo)
        self.model_protocol=QComboBox()
        self.model_protocol.addItems(['Seleccione protocolo de cm_ del ajuste','Sin corte: todos los retornos normalizados','Sólo alturas >2 m'])
        self.model_protocol.setToolTip('modelos.json no guarda el corte de las columnas cm_. Debe coincidir con su CSV de calibración. Las columnas cm_gt2_ siempre usan >2 m. FCC y P95 de salida no cambian.')
        form.addRow('Métricas estándar del ajuste',self.model_protocol)
        self.output = QLineEdit()
        self.output.setToolTip('Todos los LAZ, LAS, MDT, celdas y cálculos se guardan aquí. Debe ser un disco local, no Q: ni una unidad de red.')
        form.addRow('Procesamiento local (sin espacios)',self.path_row(self.output))
        self.final_output=QLineEdit()
        self.final_output.setToolTip('Opcional. Puede estar en Q: u otra unidad de red. Sólo recibe la cartografía terminada y sus registros, tras verificar las copias.')
        form.addRow('Destino final (opcional, admite red)',self.path_row(self.final_output))
        self.previous_run=QLineEdit()
        self.previous_run.setToolTip('Opcional. Seleccione la carpeta de una ejecución anterior que contiene estado.json. Se importan originales, LAS y celdas completadas, sin modificar el origen.')
        form.addRow('Ejecución anterior para recuperar',self.path_row(self.previous_run))
        self.downloads = QLineEdit(str(default_download_directory()))
        form.addRow('Descargas de Chrome',self.path_row(self.downloads))
        form.addRow('Descarga CNIG',QLabel('Lotes asistidos de hasta 20 hojas; selección y autorización en Chrome'))
        self.fusion = QLineEdit('C:\\FUSION')
        form.addRow('Carpeta FUSION',self.fusion)
        self.cell = QDoubleSpinBox()
        self.cell.setRange(.1,20)
        self.cell.setValue(1)
        form.addRow('Resolución del MDT (m)',self.cell)
        self.support = QDoubleSpinBox()
        self.support.setRange(.5,20)
        self.support.setValue(5)
        form.addRow('Distancia máxima de apoyo (m)',self.support)
        form_widget=QWidget()
        form_widget.setLayout(form)
        for label in form_widget.findChildren(QLabel):
            label.setWordWrap(True)
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_widget)
        layout.addWidget(scroll)
        note = QLabel('Windows · FUSION 4.61 · CRS UTM compatible con las teselas. Se incluyen celdas completas que intersectan el polígono; BORDE y FRAC_AOI identifican los bordes. Límite inicial: 10.000 celdas.')
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QHBoxLayout()
        self.start = QPushButton('Ejecutar / reutilizar datos')
        self.start.clicked.connect(self.execute)
        self.pause = QPushButton('Pausar')
        self.pause.setEnabled(False)
        self.pause.clicked.connect(self.toggle_pause)
        self.reopen = QPushButton('Volver a abrir lote')
        self.reopen.setEnabled(False)
        self.reopen.clicked.connect(self.retry_download)
        self.cancel_button = QPushButton('Cancelar')
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        self.help_button = QPushButton('Ayuda')
        self.help_button.clicked.connect(self.show_help)
        for button in (self.help_button,self.start,self.pause,self.reopen,self.cancel_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.copy_button=QPushButton('Copiar resultados locales terminados (sin recalcular)')
        self.copy_button.clicked.connect(self.copy_results)
        layout.addWidget(self.copy_button)
        self.bar = QProgressBar()
        layout.addWidget(self.bar)
        self.messages = QPlainTextEdit()
        self.messages.setReadOnly(True)
        layout.addWidget(self.messages)

    def path_row(self, edit):
        from qgis.PyQt.QtWidgets import QWidget
        box = QWidget()
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0,0,0,0)
        layout.addWidget(edit)
        button = QPushButton('…')
        def select():
            path = QFileDialog.getExistingDirectory(self,'Seleccionar carpeta')
            if path:
                edit.setText(path)
        button.clicked.connect(select)
        layout.addWidget(button)
        return box

    def execute(self):
        try:
            if os.name != 'nt':
                raise ValueError('El procesamiento FUSION requiere Windows')
            wkb, epsg = snapshot(self.layer.currentLayer())
            path=self.model_path.text().strip()
            cutoff={0:'unspecified',1:None,2:2}[self.model_protocol.currentIndex()]
            models=load_models(path or None,{output:combo.currentData() for output,combo in self.model_targets.items()},cutoff)
            if path and not any(models['mapping'].values()):
                raise ValueError('Seleccione al menos una ecuación del archivo para las variables dasométricas')
            output, downloads = self.output.text().strip(), self.downloads.text().strip()
            if not output or not Path(output).is_absolute() or any(c.isspace() for c in output):
                raise ValueError('Indique una carpeta de trabajo absoluta sin espacios')
            output=str(local_workspace(output))
            final=self.final_output.text().strip()
            previous=self.previous_run.text().strip()
            if final and not Path(final).is_absolute():
                raise ValueError('El destino final debe ser una ruta absoluta')
            if previous and not (Path(previous)/'estado.json').is_file():
                raise ValueError('La ejecución anterior debe contener estado.json; seleccione su carpeta con fecha y código')
            if not downloads or not Path(downloads).is_absolute():
                raise ValueError('Indique la carpeta absoluta de descargas de Chrome')
            config = {'output':output,'download_directory':downloads,'fusion':self.fusion.text().strip(),
                      'epsg':epsg,'cell':self.cell.value(),'support_distance':self.support.value(),
                      'batch_download':True,'batch_limit':20,'assume_missing_crs':False,
                      'final_destination':final,'previous_run':previous}
            self.job = Job(config,wkb,models)
            self.job.status.connect(self.status)
            self.job.completed.connect(self.finished)
            self.start.setEnabled(False)
            self.copy_button.setEnabled(False)
            self.pause.setText('Pausar')
            self.pause.setEnabled(True)
            self.cancel_button.setEnabled(True)
            self.messages.appendPlainText('Inicio de nueva ejecución; se reutilizan originales y conversiones verificados de esta carpeta.')
            QgsApplication.taskManager().addTask(self.job)
        except Exception as error:
            QMessageBox.warning(self,'Validación',str(error))

    def copy_results(self):
        if self.job:
            return
        final=self.final_output.text().strip()
        if not final or not Path(final).is_absolute():
            QMessageBox.warning(self,'Destino','Indique primero una carpeta absoluta en «Destino final».')
            return
        directory=QFileDialog.getExistingDirectory(self,'Ejecución local terminada (contiene cartografia_20m.shp y estado.json)')
        if not directory:
            return
        try:
            directory=str(local_workspace(directory))
            self.job=Job({'copy_run':directory,'final_destination':final},None)
            self.job.status.connect(self.status)
            self.job.completed.connect(self.finished)
            self.start.setEnabled(False)
            self.copy_button.setEnabled(False)
            self.pause.setEnabled(True)
            self.cancel_button.setEnabled(True)
            QgsApplication.taskManager().addTask(self.job)
        except Exception as error:
            QMessageBox.warning(self,'Copia',str(error))

    def status(self, n, text):
        self.bar.setValue(int(n))
        self.messages.appendPlainText(text)
        if self.job and self.job.pause_requested.is_set() and text.startswith('En pausa.'):
            self.pause.setText('Reanudar')
        self.reopen.setEnabled(self.job is not None and text.startswith(('CNIG autorización:','CNIG vigilando:','CNIG archivo completo incorporado:')))

    def choose_models(self):
        path=QFileDialog.getOpenFileName(self,'Modelos exportados por Modelización forestal LiDAR','','Modelos JSON (*.json)')[0]
        if path:
            self.model_path.setText(path)
            self.load_model_choices()

    def load_model_choices(self):
        for combo in self.model_targets.values():
            combo.clear()
            combo.addItem('(sin modelo)',None)
        path=self.model_path.text().strip()
        if not path:
            return
        try:
            package=read_package(path)
            saved=package.get('protocolo_metricas',{})
            if saved.get('known'):
                cutoff=saved['cm_standard_height_filter_m']
                self.model_protocol.setCurrentIndex(1 if cutoff is None else 2 if cutoff==2 else 0)
            for output,combo in self.model_targets.items():
                for name in package['modelos']:
                    if name not in ('Hdom','FCC_pct','D_medio_cm'):
                        combo.addItem(name,name)
                index=combo.findData(TARGETS[output])
                if index>=0:
                    combo.setCurrentIndex(index)
            self.messages.appendPlainText('Modelos cargados: '+', '.join(package['modelos'])+'. Revise la asignación, unidades y protocolo de las métricas.')
        except Exception as error:
            QMessageBox.warning(self,'Modelos',str(error))

    def toggle_pause(self):
        if not self.job or self.job.isCanceled():
            return
        if self.job.pause_requested.is_set():
            self.job.pause_requested.clear()
            self.pause.setText('Pausar')
        else:
            self.job.pause_requested.set()
            self.pause.setText('Retirar pausa')
            self.messages.appendPlainText('Pausa solicitada. El comando FUSION activo terminará antes de pausar; Chrome continúa descargando.')

    def retry_download(self):
        if self.job:
            self.job.retry.set()

    def cancel(self):
        if self.job:
            self.job.cancel()
            self.pause.setEnabled(False)
            self.messages.appendPlainText('Cancelación solicitada. Se conservan los originales; Chrome sigue abierto.')

    def finished(self, directory, error):
        previous=getattr(getattr(self.job,'engine',None),'previous',None)
        if previous and (previous.staged/'estado.json').is_file():
            self.previous_run.setText(str(previous.staged))
            self.messages.appendPlainText('Recuperación importada a disco local: '+str(previous.staged)+'. Los siguientes intentos pueden usar esta copia local.')
        self.job = None
        self.start.setEnabled(True)
        self.copy_button.setEnabled(True)
        for button in (self.pause,self.reopen,self.cancel_button):
            button.setEnabled(False)
        self.pause.setText('Pausar')
        if error:
            self.messages.appendPlainText('ERROR: '+error+'\nResultados y registro: '+directory)
        else:
            self.messages.appendPlainText('Finalizado: '+directory+'\nRevise EST_N, EST_VOL y EST_AB: indican imputación, extrapolación, dominio o ausencia de modelo.')
            layer = QgsVectorLayer(str(Path(directory)/'cartografia_20m.gpkg'),'Cartografía forestal 20 m','ogr')
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)

    def show_help(self):
        if self.help_dialog is None:
            self.help_dialog = QDialog(self)
            self.help_dialog.setWindowTitle('Ayuda · Cartografía forestal LiDAR')
            self.help_dialog.resize(760,650)
            layout = QVBoxLayout(self.help_dialog)
            browser = QTextBrowser()
            browser.setHtml((Path(__file__).parent/'AYUDA.html').read_text(encoding='utf-8'))
            browser.setOpenExternalLinks(True)
            layout.addWidget(browser)
            close = QPushButton('Cerrar')
            close.clicked.connect(self.help_dialog.close)
            layout.addWidget(close)
        self.help_dialog.show()
        self.help_dialog.raise_()

    def closeEvent(self, event):
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
    def __init__(self, iface):
        self.iface, self.dialog = iface, None

    def initGui(self):
        self.action = QAction('Cartografía forestal LiDAR 20 m',self.iface.mainWindow())
        self.action.triggered.connect(self.open)
        self.iface.addPluginToMenu('Cartografía forestal LiDAR',self.action)
        self.iface.addToolBarIcon(self.action)

    def open(self):
        if self.dialog is None:
            self.dialog = Dialog(self.iface)
        self.dialog.show()
        self.dialog.raise_()

    def unload(self):
        if self.dialog and self.dialog.job:
            self.dialog.job.cancel()
        self.iface.removePluginMenu('Cartografía forestal LiDAR',self.action)
        self.iface.removeToolBarIcon(self.action)
