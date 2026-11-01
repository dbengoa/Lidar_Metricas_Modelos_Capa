"""Inventory adapter over the same engine used by cartography."""
from ..lidar_core.engine import Engine as SharedEngine
from ..lidar_core.local_work import processing_root,local_arguments
from ..lidar_core.core import atomic_json

class Engine(SharedEngine):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.state.update(suite_version='0.1.0',module='inventario')

    def execute(self):
        self.c['output']=processing_root(self.c['output'])
        return super().execute()

    def run_command(self,args):
        return super().run_command(local_arguments(args))

    def _execute(self,root):
        super()._execute(root)
        atomic_json(self.run/'protocolo_inventario.json',{
            'suite_version':'0.1.0','epsg':self.c['epsg'],'radius_m':self.c['radius'],
            'cm_standard_height_filter_m':self.c.get('height_cutoff'),
            'fcc_threshold_m':2,'returns':'all','normalized':True})
