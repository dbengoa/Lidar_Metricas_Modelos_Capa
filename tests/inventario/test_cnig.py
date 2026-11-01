from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from lidar_forestal_integrado.lidar_core.cnig import Client,CatalogError,parse_page,prefer_versions,rank_name
from lidar_forestal_integrado.lidar_core.core import Cancelled

DATA=Path(__file__).parent/'data'


def page(records,total=None):
    rows=[]
    for sec,name in records:
        rows.append('<tr><td>'+name+'</td><td><a id="linkDescDir_'+sec+'"></a></td></tr>')
    return '<input value="LIDA3" id="codSerie"><input value="'+str(len(records) if total is None else total)+'" id="totalArchivos"><table>'+''.join(rows)+'</table>'


class CatalogTests(unittest.TestCase):
    def test_actual_official_response(self):
        rows,total=parse_page((DATA/'cnig-catalog-real.html').read_text())
        self.assertEqual(total,1)
        self.assertEqual(rows,[dict(sec='12752563',name='PNOA-2024-GAL-628-4780-H29-NPC01.LAZ',series='LIDA3')])

    def test_empty_is_distinct_from_broken_response(self):
        self.assertEqual(parse_page(page([])),([],0))
        for text in ('<html>Login</html>',page([]).replace('LIDA3','LIDA2'),page([],1)):
            with self.assertRaises(CatalogError):parse_page(text)

    def test_row_pairing_not_parallel_arrays(self):
        text=page([('1','PNOA-2024-GAL-628-4780-H29-NPC01.LAZ'),('2','PNOA-2024-GAL-629-4780-H29-NPC01.LAZ')])
        rows,total=parse_page(text)
        self.assertEqual([r['sec'] for r in rows],['1','2'])
        self.assertIn('629-4780',rows[1]['name'])
        text=text.replace('id="linkDescDir_1"','id="linkDescDir_1" extra="x"><a id="linkDescDir_99"')
        with self.assertRaises(CatalogError):parse_page(text)

    def test_pagination_and_duplicate_ids(self):
        client=Client()
        pages=[page([('1','PNOA-2024-GAL-628-4780-H29-NPC01.LAZ')],2),page([('2','PNOA-2024-GAL-629-4780-H29-NPC01.LAZ')],2)]
        with patch.object(client,'request',side_effect=pages) as req:
            rows=client.search({'type':'FeatureCollection','features':[]})
            self.assertEqual(len(rows),2)
            self.assertEqual(req.call_args_list[1].args[1]['numPagina'],'2')
            self.assertEqual(req.call_args_list[0].args[1]['codSerie'],'LIDA3')
        with patch.object(client,'request',side_effect=[pages[0],pages[0]]):
            with self.assertRaisesRegex(CatalogError,'repitió'):client.search({})

    def test_version_policy(self):
        rows=[dict(sec=str(i),name=n,series='LIDA3') for i,n in enumerate((
            'PNOA-2023-GAL-628-4780-H29-NPC03.LAZ',
            'PNOA_2024_GAL_628-4780_H29_NPC01.LAZ',
            'PNOA-2024-GAL-628-4780-H29-NPC02+.LAZ',
            'PNOA-2024-GAL-628-4780-H30-NPC03.LAZ'))]
        chosen,excluded=prefer_versions(rows,25829)
        self.assertEqual(chosen[0]['sec'],'2')
        self.assertEqual(len(excluded),3)
        with self.assertRaisesRegex(CatalogError,'dos archivos'):
            prefer_versions([rows[2],dict(rows[2],sec='999')],25829)
        with self.assertRaises(CatalogError):rank_name('arbitrary.laz')

    def test_pnr_filename_without_zone_reported_on_windows(self):
        name='PNOA-2024-PNR-523-4654-NPC01.laz'
        key,rank=rank_name(name)
        self.assertEqual(key,(523,4654,None))
        self.assertEqual(rank,(2024,1,False))
        rows,total=parse_page(page([('123',name)]))
        selected,excluded=prefer_versions(rows,25830)
        self.assertEqual(selected[0]['name'],name)
        self.assertEqual(excluded,[])

    def test_missing_zone_does_not_override_known_mismatch_or_editions(self):
        rows=[dict(sec='1',name='PNOA-2024-PNR-523-4654-NPC01.laz'),
              dict(sec='2',name='PNOA_2024_PNR_523-4654_H30_NPC02.LAZ'),
              dict(sec='3',name='PNOA-2024-PNR-523-4654-H29-NPC03.LAZ')]
        selected,excluded=prefer_versions(rows,25830)
        self.assertEqual([r['sec'] for r in selected],['2'])
        self.assertEqual({r['reason'] for r in excluded},{'different_utm_zone','older_flight_or_lower_npc'})
        with self.assertRaises(CatalogError):rank_name('PNOA-2024-PNR-523-4654-NPC01.laz/evil')

    def test_footprint_response_contract(self):
        c=Client()
        raw=(DATA/'cnig-footprint-real.json').read_text()
        with patch.object(c,'request',return_value=raw):
            self.assertEqual(c.footprint('12752563')['features'][0]['geometry']['type'],'MultiPolygon')
        with patch.object(c,'request',return_value=raw):
            with self.assertRaises(CatalogError):c.footprint('999')

    def test_cancel_before_network(self):
        def cancel():raise Cancelled('stop')
        with self.assertRaises(Cancelled):Client(cancel).search({})

if __name__=='__main__':unittest.main()
