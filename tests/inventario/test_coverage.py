"""Check the uploaded 0.4.5 first-return metric against synthetic LAS records."""
from pathlib import Path
import struct
import tempfile
import unittest

from fixtures import write_cloud
from lidar_forestal_integrado.lidar_core.coverage import first_return_cover
from lidar_forestal_integrado.lidar_core.local import MIN_RECORD


def cloud(path, fmt=0, returns=(1, 1, 1, 1, 2)):
    heights = (-1, 0, 2, 3, 5, 6)
    points = [(i, i, heights[i], 2 if i < 3 else 5) for i in range(len(returns))]
    write_cloud(path, points)
    data = bytearray(path.read_bytes())
    offset = struct.unpack_from('<I', data, 96)[0]
    old = data[offset:]
    size = MIN_RECORD[fmt]
    data[104] = fmt
    struct.pack_into('<H', data, 105, size)
    records = []
    for i, number in enumerate(returns):
        record = bytearray(size)
        record[:12] = old[i*20:i*20+12]
        record[14] = number | (16 if fmt >= 6 else 8)
        record[16 if fmt >= 6 else 15] = points[i][3]
        records.append(record)
    path.write_bytes(data[:offset] + b''.join(records))


class CoverageTests(unittest.TestCase):
    def test_all_formats_and_ground_in_denominator(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'normalized.las'
            for fmt in range(11):
                with self.subTest(format=fmt):
                    cloud(path, fmt)
                    before = path.read_bytes()
                    result = first_return_cover(path, 2)
                    self.assertEqual(result['n_primeros_retornos'], 4)
                    self.assertEqual(result['n_primeros_retornos_sobre_corte'], 1)
                    self.assertEqual(result['cobertura_primeros_retornos_pct'], 25)
                    self.assertEqual(path.read_bytes(), before)

    def test_ninth_return_is_not_first(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'normalized.las'
            cloud(path, 6, (1, 1, 1, 1, 2, 9))
            self.assertEqual(first_return_cover(path)['n_primeros_retornos'], 4)

    def test_empty_denominator_differs_from_zero_cover(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'normalized.las'
            cloud(path, returns=(2, 2, 2, 2, 2))
            result = first_return_cover(path)
            self.assertEqual(result['estado_cobertura'], 'sin_primeros_retornos')
            self.assertEqual(result['cobertura_primeros_retornos_pct'], '')
            cloud(path)
            self.assertEqual(first_return_cover(path, 10)['cobertura_primeros_retornos_pct'], 0)

    def test_truncated_cloud_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'normalized.las'
            cloud(path)
            path.write_bytes(path.read_bytes()[:-1])
            with self.assertRaises(ValueError):
                first_return_cover(path)


if __name__ == '__main__':
    unittest.main()
