# Work package 5.1.1: earthquake parameters

Estimate earthquake parameters from seismic waveforms. This workspace uses the
shared `../data/` directory; raw waveforms must not be copied here.

## First milestone: inspect the data

From the repository root:

```bash
python3 -m venv 511/.venv
511/.venv/bin/python -m pip install -r 511/requirements-lock.txt
511/.venv/bin/python 511/inventory.py
511/.venv/bin/python -m unittest discover -s 511/tests -v
```

The lock file records the environment validated on Linux with Python 3.14.7.
`requirements.txt` lists direct dependency ranges for resolving a new environment.
If `venv` reports missing `ensurepip`, install your distribution's Python venv
package or bootstrap pip inside a `--without-pip` environment using the official
https://bootstrap.pypa.io/get-pip.py script.

The inventory decodes each MiniSEED file separately, records trace metadata and
raw sample statistics, and reports gaps, overlaps, reader warnings, constant
traces, and unreadable files. It writes `outputs/inventory/inventory.json` and
`traces.csv`; generated outputs and the virtual environment are ignored by Git.
Paths default to this repository regardless of the current working directory.
Use `--data-dir` and `--output-dir` to inspect a different dataset.

Gap checks operate within each file. Cross-file continuity, component alignment,
instrument response, clipping, event identification, and signal quality need
additional checks. Raw sample amplitudes are not calibrated physical units.
Warnings and discontinuities require review even when the command exits zero;
unreadable files produce an exit status of one.

## Research sequence

1. Inventory waveform timing, sampling rates, discontinuities, and station channels.
2. Obtain station coordinates, instrument responses, event origin times,
   hypocenters, magnitude types/values, and analyst P/S arrival labels.
3. Define the first prediction target and an evaluation dataset. Separate events
   between training and evaluation; assess transfer to the Vietnamese stations.
4. Establish phase-picking and event association/location baselines, followed by
   magnitude estimation. Record preprocessing, model versions, uncertainty, and
   errors for each stage before integrating with `../vasteq/`.

This sequence is provisional until the first model target is chosen. The local
`refs/2_PhaseNet.pdf` and `refs/2_LOC_FLOW_Zhang_SRL_2022.pdf` describe relevant
phase-picking and location workflows. No model is trained yet. Directory names
such as `data/samples/4.0` must not be treated as magnitude labels without a
documented event catalog.

## Metadata needed

The [sample metadata audit](../docs/511-sample-metadata.md) confirms that station
coordinates are absent from all 679,131 waveform records. Run
`511/.venv/bin/python 511/inspect_metadata.py` from the repository root to produce
the per-file header audit and station table under `511/outputs/metadata/`.

The subsequently supplied `data/stations.xlsx` provides coordinates for all 20
stations; see the [spreadsheet analysis](../docs/511-station-spreadsheet.md).
Its coordinate datum, response calibration, and deployment validity dates remain
unspecified. The waveform-header station table still describes headers alone.

- Stations: network, station, location, latitude, longitude, elevation, channel
  orientations, response metadata, and validity dates.
- Events: event ID, UTC origin time, latitude, longitude, depth in km, magnitude,
  magnitude type, provenance, and uncertainties.
- Picks: event ID, waveform trace ID, phase, UTC arrival time, quality/uncertainty,
  and provenance.

Define these schemas alongside the source catalogs before constructing training
examples. NumPy and ObsPy are the initial inspection dependencies. Add and pin
training dependencies when the first experiment is defined.

## Initial sample findings

The first decoded inventory of `data/samples/4.0` found:

- 60 readable files, 20 stations, and HLE/HLN/HLZ channels at 100 Hz.
- 444 trace segments containing 486,606,896 samples.
- Overall time bounds: 2026-10-02 00:00:01.280 UTC through
  2026-10-03 00:00:01.960 UTC; these bounds do not imply continuous coverage.
- 147 gaps and 39 overlaps within files.
- No reader warnings, constant trace segments, or nonfinite samples.

These findings verify decoding and identify timing issues; they do not establish
event labels, calibration, clipping status, or readiness for model training.

ObsPy API reference: https://docs.obspy.org/packages/autogen/obspy.core.stream.Stream.html
