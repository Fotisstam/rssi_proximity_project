# RSSI Proximity

Estimates whether you are **near (ΚΟΝΤΑ)**, at **medium distance (ΜΕΤΡΙΑ ΑΠΟΣΤΑΣΗ)** or **far (ΜΑΚΡΙΑ)** from a fixed
Wi-Fi access point, using only the received signal strength (RSSI). No coordinates are computed.

## Run (Windows)

```
pip install -r requirements.txt
python main.py
```

`python main.py --simulate` uses a synthetic signal instead of Wi-Fi (the default on non-Windows systems), so you
can try the whole workflow first. A "Simulated position" selector and an "obstacle" attenuation box appear in the toolbar.

## Workflow (one tab per step)

1. **Select access point...** (toolbar) scans and lists networks per BSSID. Pick the AP and leave
   "Lock to this exact BSSID" ticked. **Start scanning** begins reading RSSI.
2. **Calibrate tab**
   - Stand at each zone, keep the device orientation fixed, press **Record**. Each run is saved as
     `calibration_<time>_<zone>.csv` in the data folder (default `~/RSSI Proximity/data`).
     Record each zone more than once, at different moments, for a better representative value.
   - Choose the smoothing (moving average / median, window) and press **Compute from calibration CSVs**.
     This gives the representative RSSI of each zone (median or mean) and two thresholds
     (midpoint, or weighted by each zone's spread). Saved to `model.json`.
3. **Live tab** shows the estimated class from the smoothed signal. A hysteresis margin (default 1 dB)
   stops the label flickering at a threshold.
4. **Evaluate tab**: record a **Test set** on the Calibrate tab (another time, same zone positions;
   use the *Condition* field for "behind wall", "device upright", ...). Then press
   **Use test CSVs from data folder**. You get the percentage of correct classifications, a confusion matrix,
   accuracy per condition, and a generated commentary on the effect of obstacles and device orientation.
   Warnings appear if calibration data is used for the evaluation.

## CSV format

`timestamp, epoch_s, dataset, session, zone, distance_m, condition, ssid, bssid, signal_pct, rssi_dbm, source`

`zone` is `near`, `medium` or `far`. `source` is `interface` (the AP you are connected to) or `scan`.

## Windows notes

- Windows reports signal *quality* (0-100 %). It is converted with `dBm = percent / 2 - 100`, an approximation
  (100 % = -50 dBm, 0 % = -100 dBm). Mention this in the report.
- If you are connected to the chosen AP, readings come from `netsh wlan show interfaces` (about 1 Hz).
  For any other AP they come from `netsh wlan show networks mode=bssid`, which Windows refreshes only every few
  seconds, so consecutive values can repeat. For the cleanest data, connect to the AP you measure.
- If the AP list stays empty, enable Settings > Privacy & security > Location (and "Let desktop apps access your
  location"); recent Windows 11 builds block Wi-Fi scans without it.
- The parser does not depend on the Windows language (it works on a Greek Windows).

## Layout

```
main.py
rssi_proximity/
  acquisition/  netsh.py (parsing + subprocess), backends.py (Netsh, Simulated)
  storage/      csv_logger.py (one CSV per run, loading)
  processing/   filters.py (causal moving average / median), stats.py
  classify/     model.py (thresholds, classifier, hysteresis), evaluate.py, commentary.py
  gui/          main_window, calibrate_tab, live_tab, evaluate_tab, ssid_dialog, state, workers, theme (from EEG Studio)
tests/test_logic.py      python -m unittest discover -s tests
```

The logic packages do not import Qt, so they can be tested and reused without the GUI.
