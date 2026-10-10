import importlib.util
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location("import_stations", Path(__file__).resolve().parents[1] / "import_stations.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def workbook(path, rows):
    namespace = module.NS["s"]
    sheet = ET.Element(f"{{{namespace}}}worksheet")
    data = ET.SubElement(sheet, f"{{{namespace}}}sheetData")
    for number, values in enumerate([module.HEADERS] + rows, 1):
        row = ET.SubElement(data, f"{{{namespace}}}row", r=str(number))
        for column, value in zip("ABCDEFGH", values):
            cell = ET.SubElement(row, f"{{{namespace}}}c", r=f"{column}{number}", t="inlineStr")
            ET.SubElement(ET.SubElement(cell, f"{{{namespace}}}is"), f"{{{namespace}}}t").text = value
    merged = ET.SubElement(sheet, f"{{{namespace}}}mergeCells")
    ET.SubElement(merged, f"{{{namespace}}}mergeCell", ref="A2:A3")
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", f'<workbook xmlns="{namespace}" xmlns:r="{module.REL}"><sheets><sheet name="Sheet1" r:id="rId1"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr("xl/worksheets/sheet1.xml", ET.tostring(sheet))


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.path = self.directory / "stations.xlsx"
        self.rows = [
            ["Sơn La", "1", "4001", "21.235880", "104.016949", "Trường học", "S303", "007704"],
            ["", "2", "4002", "21.289420", "103.994389", "Trường khác", "Palert", "2421"],
        ]
        for code in ["4001", "4002"]:
            (self.directory / f"VN.{code}..HLZ.2026.275.mseed").touch()

    def parse(self):
        workbook(self.path, self.rows)
        return module.parse_stations(self.path, waveform_dir=self.directory)

    def test_merged_province_and_coordinate_headers(self):
        stations = self.parse()
        self.assertEqual(stations[1]["province"], "Sơn La")
        self.assertEqual(stations[0]["latitude"], "21.235880")
        self.assertEqual(stations[0]["longitude"], "104.016949")
        self.assertEqual(stations[0]["instrument_serial"], "007704")

    def test_duplicate_codes_rejected(self):
        self.rows[1][2] = "4001"
        with self.assertRaisesRegex(ValueError, "duplicate station"):
            self.parse()

    def test_swapped_coordinates_rejected(self):
        self.rows[0][3], self.rows[0][4] = self.rows[0][4], self.rows[0][3]
        with self.assertRaisesRegex(ValueError, "coordinate range"):
            self.parse()

    def test_missing_waveform_match_rejected(self):
        self.rows[1][2] = "9999"
        with self.assertRaisesRegex(ValueError, "network match"):
            self.parse()

    def test_sql_has_transaction_and_preserves_unrelated_fields(self):
        sql = module.generate_sql(self.parse(), "data/stations.xlsx", "a" * 64)
        self.assertIn("START TRANSACTION;", sql)
        self.assertTrue(sql.endswith("COMMIT;\n"))
        self.assertIn("coordinate_crs = NULL", sql)
        self.assertNotIn("city =", sql)
        self.assertNotIn("elevation_m =", sql)
        self.assertNotIn("id =", sql)
        self.assertIn("ON DUPLICATE KEY UPDATE", sql)
        self.assertEqual(module.sql_string("a'\\b"), "CONVERT(X'61275c62' USING utf8mb4)")
