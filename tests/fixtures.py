from pathlib import Path
import struct


def write_cloud(path, points=None, epsg=25830, wkt=None, evlr=False, compressed=False, version=4):
    if points is None:
        points=[(400000.5,4600000.5,100,2),(400001.5,4600001.5,110,5)]
    projection=[]
    if epsg is not None:
        projection.append((34735,struct.pack('<8H',1,1,0,1,3072,0,1,epsg)))
    if wkt:
        projection.append((2112,wkt.encode()+b'\0'))
    vlrs=b'';evlrs=b''
    for rid,data in projection:
        if evlr:
            evlrs+=struct.pack('<H16sHQ32s',0,b'LASF_Projection',rid,len(data),b'CRS')+data
        else:
            vlrs+=struct.pack('<H16sHH32s',0,b'LASF_Projection',rid,len(data),b'CRS')+data
    header_size=375 if version>=4 else 227
    h=bytearray(header_size)
    h[:4]=b'LASF';h[24:26]=bytes((1,version))
    struct.pack_into('<H',h,94,header_size)
    struct.pack_into('<I',h,96,header_size+len(vlrs))
    struct.pack_into('<I',h,100,0 if evlr else len(projection))
    h[104]=128 if compressed else 0
    struct.pack_into('<H',h,105,20)
    struct.pack_into('<I',h,107,len(points))
    struct.pack_into('<ddd',h,131,.01,.01,.01)
    xs,ys,zs,cs=zip(*points)
    struct.pack_into('<6d',h,179,max(xs),min(xs),max(ys),min(ys),max(zs),min(zs))
    records=b''.join(struct.pack('<iiiHBBbBH',round(x*100),round(y*100),round(z*100),50,9,c,0,0,1) for x,y,z,c in points)
    if compressed:records=b'x' # Structural metadata fixture, not a real LAZ stream.
    if version>=4:
        struct.pack_into('<Q',h,247,len(points))
        if evlr:
            struct.pack_into('<Q',h,235,header_size+len(vlrs)+len(records))
            struct.pack_into('<I',h,243,len(projection))
    Path(path).write_bytes(h+vlrs+records+evlrs)


def four_tiles(folder):
    paths=[]
    for i,(x0,y0) in enumerate(((-20,-20),(0,-20),(-20,0),(0,0))):
        p=Path(folder)/('tile '+str(i)+'.las')
        points=[(400000+x0+x+.5,4600000+y0+y+.5,z,c) for x in range(20) for y in range(20) for z,c in ((100,2),(110,5))]
        write_cloud(p,points)
        paths.append(str(p))
    return paths
