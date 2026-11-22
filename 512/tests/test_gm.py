"""Tests for 5.1.2 that need no external data. Run from repository root:

    python -m unittest discover -s 512/tests -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gm import scenario, synth  # noqa: E402
from gm.baseline import BaselineGMPE  # noqa: E402
from gm.evaluate import grouped_cv, residual_components  # noqa: E402
from gm.features import FEATURES, feature_frame, target_vector  # noqa: E402
from gm.fetch_shakemap import parse_stationlist  # noqa: E402
from gm.flatfile import COLUMNS, clean, haversine_km, read_nga_west2  # noqa: E402
from gm.models import make_model  # noqa: E402
from gm.vs30 import grid_over_bbox, read_stations  # noqa: E402


class FlatfileTests(unittest.TestCase):
    def test_haversine(self):
        self.assertAlmostEqual(haversine_km(21.0, 103.0, 21.0, 104.0), 103.8, delta=1.0)
        self.assertAlmostEqual(haversine_km(21.0, 103.0, 22.0, 103.0), 111.2, delta=0.5)

    def test_synthetic_schema(self):
        df = synth.make_flatfile(5, seed=1)
        self.assertEqual(list(df.columns), COLUMNS)
        self.assertTrue((df["pga_g"] > 0).all())
        self.assertEqual(df["event_id"].nunique(), 5)

    def test_clean_drops_bad_rows(self):
        df = synth.make_flatfile(3, seed=2)
        df.loc[0, "mag"] = 2.0
        df.loc[1, "rhypo_km"] = 900.0
        df.loc[2, "pga_g"] = 0.0
        out = clean(df)
        self.assertEqual(len(out), len(df) - 3)

    def test_nga_reader_with_fuzzy_headers(self):
        raw = pd.DataFrame({
            "EQID": [1, 1, 2], "Station Sequence Number": [10, 11, 12],
            "Earthquake Magnitude": [6.0, 6.0, 5.0], "Hypocenter Depth (km)": [10, 10, 8],
            "Hypocenter Latitude (deg)": [34, 34, 35], "Hypocenter Longitude (deg)": [-118, -118, -119],
            "Station Latitude": [34.1, 34.2, 35.1], "Station Longitude": [-118.1, -118.2, -119.1],
            "HypD (km)": [15, 25, 20], "EpiD (km)": [11, 23, 18], "Joyner-Boore Dist. (km)": [10, 22, 17],
            "ClstD (km)": [12, 23, 18], "Vs30 (m/s) selected for analysis": [500, 300, -999],
            "Mechanism Based on Rake Angle": [0, 0, 2], "PGA (g)": [0.3, 0.1, 0.05], "PGV (cm/sec)": [20, 8, 4],
            "T0.300S": [0.5, 0.2, 0.1], "T1.000S": [0.2, 0.08, 0.03], "T3.000S": [0.05, 0.02, 0.01],
        })
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "nga.csv"
            raw.to_csv(path, index=False)
            df = read_nga_west2(path)
        self.assertEqual(len(df), 3)
        self.assertEqual(list(df["mech"]), ["SS", "SS", "RV"])
        self.assertTrue(np.isnan(df.loc[2, "vs30_ms"]))
        self.assertAlmostEqual(df.loc[0, "sa_1.0_g"], 0.2)


class ShakeMapParserTests(unittest.TestCase):
    def test_parse_stationlist(self):
        geojson = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "id": "NC.J051", "geometry": {"type": "Point", "coordinates": [-121.0, 37.0]},
             "properties": {"station_type": "seismic", "network": "NC", "code": "J051", "pga": "12.5", "pgv": "8.1",
                            "distances": {"rhypo": 20.0, "rjb": 15.0, "rrup": 16.0},
                            "channels": [
                                {"name": "HNE", "amplitudes": [
                                    {"name": "pga", "value": 12.5, "units": "%g", "flag": "0"},
                                    {"name": "sa(0.3)", "value": 25.0, "units": "%g", "flag": "0"},
                                    {"name": "sa(1.0)", "value": "null", "units": "%g", "flag": "0"}]},
                                {"name": "HNN", "amplitudes": [
                                    {"name": "pga", "value": 10.0, "units": "%g", "flag": "0"},
                                    {"name": "sa(0.3)", "value": 30.0, "units": "%g", "flag": "T"}]}]}},
            {"type": "Feature", "id": "DYFI.1", "geometry": {"type": "Point", "coordinates": [-121.1, 37.1]},
             "properties": {"station_type": "macroseismic", "network": "DYFI", "intensity": 5.0}},
        ]}
        event = {"id": "us1000", "mag": 5.5, "depth_km": 10.0, "lat": 37.1, "lon": -121.2}
        df = parse_stationlist(geojson, event)
        self.assertEqual(len(df), 1)
        r = df.iloc[0]
        self.assertAlmostEqual(r["pga_g"], 0.125)
        self.assertAlmostEqual(r["sa_0.3_g"], 0.25)  # flagged 30 %g channel ignored
        self.assertTrue(np.isnan(r["sa_1.0_g"]))
        self.assertAlmostEqual(r["pgv_cms"], 8.1)
        self.assertEqual(r["rjb_km"], 15.0)
        self.assertEqual(r["station_id"], "NC.J051")


    def test_parse_shakemap35_names(self):
        geojson = {"features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [-117.5, 35.7]},
                                 "properties": {"network": "CI", "code": "CLC", "pga": 20.0, "pgv": 15.0, "distance": 12.0,
                                                "channels": [{"name": "HNE", "amplitudes": [
                                                    {"name": "pga", "value": 20.0, "units": "%g", "flag": "0"},
                                                    {"name": "psa03", "value": 40.0, "units": "%g", "flag": "0"},
                                                    {"name": "psa10", "value": 10.0, "units": "%g", "flag": "0"},
                                                    {"name": "psa30", "value": 2.0, "units": "%g", "flag": "0"}]}]}}]}
        df = parse_stationlist(geojson, {"id": "ci1", "mag": 6.4, "depth_km": 10.0, "lat": 35.7, "lon": -117.5})
        r = df.iloc[0]
        self.assertAlmostEqual(r["sa_0.3_g"], 0.40)
        self.assertAlmostEqual(r["sa_1.0_g"], 0.10)
        self.assertAlmostEqual(r["sa_3.0_g"], 0.02)
        self.assertTrue(np.isnan(r["vs30_ms"]))


    def test_vertical_channel_excluded_by_default(self):
        feat = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-117.5, 35.7]},
                "properties": {"network": "CI", "code": "ABC", "distance": 20.0, "channels": [
                    {"name": "HNZ", "amplitudes": [{"name": "pga", "value": 50.0, "units": "%g", "flag": "0"}]},
                    {"name": "HNE", "amplitudes": [{"name": "pga", "value": 20.0, "units": "%g", "flag": "0"}]},
                    {"name": "HNN", "amplitudes": [{"name": "pga", "value": 30.0, "units": "%g", "flag": "0"}]}]}}
        ev = {"id": "e", "mag": 5.0, "depth_km": 8.0, "lat": 35.7, "lon": -117.5}
        self.assertAlmostEqual(parse_stationlist({"features": [feat]}, ev).iloc[0]["pga_g"], 0.30)
        self.assertAlmostEqual(parse_stationlist({"features": [feat]}, ev, components="all").iloc[0]["pga_g"], 0.50)


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = synth.make_flatfile(120, seed=3)
        cls.X = feature_frame(cls.df)
        cls.y = target_vector(cls.df, "pga_g")
        cls.groups = cls.df["event_id"].to_numpy()

    def test_feature_columns(self):
        self.assertEqual(list(self.X.columns), FEATURES)
        self.assertTrue(np.isfinite(self.X.to_numpy()).all())

    def test_baseline_recovers_truth_shape(self):
        model = BaselineGMPE().fit(self.X, self.y)
        c = model.summary()
        truth = synth.TRUTH["pga_g"]
        self.assertAlmostEqual(c["c1"], truth[1], delta=0.25)   # magnitude scaling
        self.assertAlmostEqual(c["c3"], truth[3], delta=0.25)   # geometric spreading
        self.assertAlmostEqual(c["c6"], truth[6], delta=0.25)   # site term
        self.assertLess(model.rmse_, 0.8)

    def test_grouped_cv_sigma_close_to_truth(self):
        tau_true, phi_true = synth.TRUTH["pga_g"][8:10]
        for name in ["baseline", "gbm"]:
            _, m = grouped_cv(make_model(name), self.X, self.y, self.groups, n_splits=5)
            self.assertLess(m["rmse"], 0.9, name)
            self.assertGreater(m["r2"], 0.8, name)
            self.assertAlmostEqual(m["phi"], phi_true, delta=0.15, msg=name)
            self.assertAlmostEqual(m["tau"], tau_true, delta=0.2, msg=name)

    def test_models_fit_predict(self):
        for name in ["rf", "mlp"]:
            m = make_model(name).fit(self.X, self.y)
            pred = m.predict(self.X)
            self.assertEqual(pred.shape, self.y.shape)
            self.assertLess(np.sqrt(np.mean((pred - self.y) ** 2)), 0.9, name)

    def test_residual_components(self):
        rng = np.random.default_rng(0)
        groups = np.repeat(np.arange(200), 20)
        resid = np.repeat(rng.normal(0, 0.3, 200), 20) + rng.normal(0, 0.5, 4000)
        c = residual_components(resid, groups)
        self.assertAlmostEqual(c["tau"], 0.3, delta=0.05)
        self.assertAlmostEqual(c["phi"], 0.5, delta=0.03)


class ScenarioTests(unittest.TestCase):
    def test_config_and_map(self):
        cfg = scenario.load_config()
        self.assertIn("lai_chau", cfg["cities"])
        self.assertIn("tuan_giao_1983", cfg["scenarios"])
        df = synth.make_flatfile(60, seed=4)
        X, y = feature_frame(df), target_vector(df, "pga_g")
        bundle = {"model": BaselineGMPE().fit(X, y), "target": "pga", "distance": "rhypo"}
        grid = grid_over_bbox(None, cfg["cities"]["lai_chau"]["bbox"], 0.02)
        scn = dict(cfg["scenarios"]["extreme_lai_chau"], id="x")
        table = scenario.predict_map(bundle, scn, grid)
        self.assertEqual(len(table), len(grid))
        self.assertTrue((table["pga"] > 0).all())
        # attenuation: the node closest to the epicentre has the largest PGA
        self.assertEqual(table["pga"].idxmax(), table["repi_km"].idxmin())
        with tempfile.TemporaryDirectory() as d:
            stem = scenario.write_outputs(table, "pga", d, "t", 0.02, scn)
            self.assertTrue(stem.with_suffix(".csv").exists())
            self.assertTrue(stem.with_suffix(".png").exists())

    def test_read_stations_vietnamese_headers(self):
        df = pd.DataFrame({"Tỉnh": ["Sơn La"], "STT": [1], "Mã trạm": [4001], "Vĩ độ": ["21.2"], "Kinh độ": ["104.0"]})
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.csv"
            df.to_csv(p, index=False)
            st = read_stations(p)
        self.assertEqual(list(st.columns[:0]), [])
        self.assertAlmostEqual(st.loc[0, "lat"], 21.2)
        self.assertEqual(st.loc[0, "station"], 4001)


class TrainFilterTests(unittest.TestCase):
    def test_magnitude_distance_cutoff_and_sigma_bins(self):
        from gm import train

        self.assertEqual(list(train.magnitude_distance_limit([4.0, 5.0, 7.0], 300.0)), [80.0, 200.0, 300.0])
        df = synth.make_flatfile(80, seed=7)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ff.csv"
            df.to_csv(path, index=False)
            table = train.run(path, Path(d) / "out", ["pga"], ["baseline"], plots=False, mag_dist_cutoff=True,
                              max_dist=300.0)
            kept = json.loads((Path(d) / "out" / "run.json").read_text())["n_rows"]
        limit = train.magnitude_distance_limit(df["mag"], 300.0)
        self.assertEqual(kept, int((df["rhypo_km"] <= limit).sum()))
        self.assertTrue(any(c.startswith("cv_sigma_M") for c in table.columns))


if __name__ == "__main__":
    unittest.main()
