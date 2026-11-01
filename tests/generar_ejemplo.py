"""Datos artificiales para comprobar el programa, sin parcelas ni resultados reales."""
from pathlib import Path
import argparse
import numpy as np
import pandas as pd


def generate(n=80, seed=47):
    rng=np.random.default_rng(seed)
    ids=[f'{i:03d}' for i in range(1,n+1)]
    h=rng.uniform(7,30,n);cover=rng.uniform(.2,.85,n);density=rng.uniform(5,20,n)
    field=pd.DataFrame({'parcela_id':ids,'V_ha':1.8*h**1.45*cover**.7*np.exp(rng.normal(0,.05,n)),
       'G_ha':5+.8*h+12*cover+rng.normal(0,.6,n),'N_ha':200+24*density+350*cover+rng.normal(0,20,n),
       'Hdom':1.2+1.04*h+rng.normal(0,.25,n),'bloque':[f'B{i%10}' for i in range(n)]})
    lidar=pd.DataFrame({'parcela_id':ids,'radio_m':15,'n_puntos':np.round(density*np.pi*15**2).astype(int),
       'cm_Elev P95':h,'cm_Elev P90':.94*h+rng.normal(0,.01,n),'cm_Canopy relief ratio':cover,
       'cm_Elev minimum':rng.normal(-.1,.05,n),'cm_Elev stddev':rng.uniform(1,8,n),
       'cm_Elev constant':1,'cm_Int mean':rng.uniform(1000,15000,n)})
    return field,lidar


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--salida',default='ejemplo');parser.add_argument('--n',type=int,default=80)
    args=parser.parse_args();folder=Path(args.salida)
    if args.n<20:parser.error('Use al menos 20 parcelas artificiales')
    if folder.exists() and any(folder.iterdir()):parser.error('Use carpeta nueva o vacía')
    folder.mkdir(parents=True,exist_ok=True)
    field,lidar=generate(args.n)
    for name,frame in [('campo.csv',field),('metricas.csv',lidar)]:frame.to_csv(folder/name,index=False,encoding='utf-8-sig')
    print('Ejemplo SINTÉTICO:',folder.resolve())
