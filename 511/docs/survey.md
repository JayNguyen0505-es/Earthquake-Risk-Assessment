# Literature Survey: Machine Learning and Deep Learning Methods for Earthquake Parameter Estimation and Seismic Risk

This document provides a systematic review of existing methodologies relevant to **Work Package 5.1.1** (*Machine learning and deep learning models for determining earthquake parameters*) and their interfaces with downstream ground-motion prediction (**Work Package 5.1.2**) and decision-support risk workflows (**Work Package 6**). The review synthesizes the papers provided in [`refs/`](../../refs).

---

## 1. Context & Problem Formulation for Work Package 5.1.1

The objective of Work Package 5.1.1 within the VAST-Earthquake 4.0 system is the automated determination of seismic event parameters:
- **Phase arrival times**: High-precision picking of compressional ($P$) and shear ($S$) wave arrivals.
- **Phase association**: Linking discrete phase picks across distributed sensors to candidate earthquake origins.
- **Event hypocenters**: Estimating origin time $T_0$, epicentral coordinates (latitude, longitude), and focal depth $z$.
- **Earthquake magnitude**: Estimating event magnitude ($M_L$, $M_w$).

### Local Dataset Characteristics & Constraints
- **Sensors**: 20 monitoring stations located in Northwest Vietnam (Sơn La, Điện Biên, Lai Châu), identified as `VN.4001` through `VN.4020`.
- **Waveform Data**: 60 MiniSEED records in `data/samples/4.0`, sampled at 100 Hz across three components (`HLE`, `HLN`, `HLZ`).
- **Station Coordinates**: Sourced from `data/stations.xlsx` (latitude: $21.208065^\circ$ to $22.408107^\circ$; longitude: $102.984729^\circ$ to $104.016949^\circ$). The coordinate datum (CRS) and instrument response functions are pending from data providers.
- **Methodological Implications**: As confirmed in literature (e.g., LOC-FLOW), **instrument response deconvolution is not required for phase picking or arrival-time cross-correlation**, but **is required for physical amplitude-based magnitude estimation**.

---

## 2. Taxonomy of Reference Literature

The reference library in [`refs/`](../../refs) spans seismological source estimation, ground-motion modeling, structural fragility, and regional risk assessment:

| Reference File | Citation / Authors | Domain / Scope | Work Package |
| :--- | :--- | :--- | :--- |
| [`2_PhaseNet.pdf`](../../refs/2_PhaseNet.pdf) | Zhu & Beroza (2019), *Geophys. J. Int.* | Deep 1D U-Net for seismic $P$ and $S$ arrival picking | **5.1.1** |
| [`2_LOC_FLOW_Zhang_SRL_2022.pdf`](../../refs/2_LOC_FLOW_Zhang_SRL_2022.pdf) | Zhang et al. (2022), *Seismol. Res. Lett.* | End-to-end ML location workflow (PhaseNet + REAL + HypoInverse + hypoDD) | **5.1.1** |
| [`3_PGA_ML.pdf`](../../refs/3_PGA_ML.pdf) | Khosravikia & Clayton (2021), *Comput. Geosci.* | ML for ground-motion intensity prediction (ANN, RF, SVM for PGA/PSA) | **5.1.2** |
| [`reviewdl.pdf`](../../refs/reviewdl.pdf) | Xie (McGill University), *Comprehensive Review* | Deep learning across earthquake engineering (CNN, RNN, GNN, RL, TL) | **5.1.1 / 5.1.2 / 6** |
| [`review.pdf`](../../refs/review.pdf) | Xie et al. (2020), *Earthquake Spectra* | Machine learning state-of-the-art review in earthquake engineering | **5.1.1 / 5.1.2 / 6** |
| [`1_Final Hanoi_Risk_E_2025.pdf`](../../refs/1_Final%20Hanoi_Risk_E_2025.pdf) | Hanoi Urban Seismic Risk (2025) | HAZUS adaptation to Vietnam urban building stock & casualty dynamics | **6** |
| [`4_RisK_MK_1.pdf`](../../refs/4_RisK_MK_1.pdf) | Tang et al. (2022), *J. Earthq. Eng.* | Fast ML-based structural seismic risk assessment | **6** |
| [`4_RISK_ML_2.pdf`](../../refs/4_RISK_ML_2.pdf) | Esteghamati & Baddipalli (2024), *Earthq. Eng. Struct. Dyn.* | Design-oriented explainable ML (SHAP) across PBEE steps | **6** |
| [`4_RISK_ML_3.pdf`](../../refs/4_RISK_ML_3.pdf) | Ding et al. (2025), *Int. J. Disaster Risk Reduct.* | Probabilistic ML & Poisson Binomial distribution for regional portfolios | **6** |

---

## 3. Core Methods for Work Package 5.1.1

### 3.1 PhaseNet: Deep-Neural-Network-Based Arrival Picking
*Source: Zhu & Beroza (2019)*

#### Architecture
PhaseNet adapts the U-Net architecture from biomedical image segmentation to 1D continuous seismic time-series:
- **Input Dimension**: $(B, 3, 3001)$ corresponding to 3-component waveforms (`HLZ`, `HLN`, `HLE`) sampled at 100 Hz over a 30-second window.
- **Contracting Path (Encoder)**: 4 stages of 1D convolutions with kernel size $7$, stride $4$, followed by Batch Normalization and ReLU activations. This condenses the temporal length by a factor of 4 per stage while expanding feature channels ($3 \to 8 \to 16 \to 32 \to 64$).
- **Expanding Path (Decoder)**: 4 stages of 1D transposed convolutions (deconvolutions) with kernel size $7$ and stride $4$.
- **Skip Connections**: Direct feature concatenation between matching encoder and decoder levels to preserve high-frequency phase-onset timing details.
- **Output Layer**: A $1 \times 1$ convolution mapping to 3 output channels ($P$-phase, $S$-phase, noise), followed by Softmax normalization along the class axis.

#### Supervision Target & Loss Formulation
Unlike binary thresholding, PhaseNet formulates pick labels as continuous probability distributions. For an arrival picked at index $t_0$, the true probability label $y_i(t)$ is modeled as a truncated Gaussian:
$$y_i(t) = \exp\left(-\frac{(t - t_0)^2}{2\sigma^2}\right), \quad |t - t_0| \le w$$
where $\sigma = 0.1\text{ s}$ ($10\text{ samples}$ at 100 Hz) and half-window width $w = 0.2\text{ s}$.

The objective function is the multi-class cross-entropy loss over time steps $t = 1, \dots, T$:
$$\mathcal{L} = -\frac{1}{T} \sum_{t=1}^{T} \sum_{k \in \{P, S, \text{Noise}\}} y_k(t) \log \hat{y}_k(t)$$

#### Key Strengths for VAST-Earthquake
1. **Handling $S$-Waves**: Traditional pickers (STA/LTA, Baer-Kradolfer) fail frequently on $S$-waves because they are buried in the coda of preceding $P$-waves. PhaseNet maintains high precision on $S$-arrivals without requiring prior $P$-coda filtering.
2. **Robustness to Low SNR**: Demonstrated strong generalization across instruments and noisy background environments.
3. **Uncertainty Quantification**: Output peak heights represent phase probabilities, and peak widths directly quantify arrival-time uncertainty ($\sigma_t$), providing required weights for subsequent hypocenter inversion.

---

### 3.2 LOC-FLOW: End-to-End High-Precision Location Workflow
*Source: Zhang et al. (2022)*

LOC-FLOW establishes a modular, automated framework integrating ML picking with regional catalog construction.

```
Continuous Waveforms (3-Component, 100 Hz)
                │
                ▼
┌───────────────────────────────────────────────┐
│ Step 1: Preprocessing & Standardization       │
│ - Zero-phase bandpass filtering               │
│ - Interpolation to uniform 100 Hz             │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────┐
│ Step 2: ML Phase Picking (PhaseNet)           │
│ - P & S probabilities, arrival times, errors  │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────┐
│ Step 3: Phase Association (REAL)              │
│ - Spatial-temporal grid search                │
│ - Associate station picks to event origins    │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────┐
│ Step 4: Velocity Inversion & Absolute Location│
│ - VELEST: Optimal 1D crustal velocity model   │
│ - HYPOINVERSE: Absolute hypocenter (T₀,x,y,z) │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────┐
│ Step 5: Double-Difference Relocation          │
│ - hypoDD / GrowClust                          │
│ - Waveform cross-correlation differential dt  │
└───────────────────────────────────────────────┘
```

#### Detailed Workflow Components
1. **Data Preprocessing**: Continuous streams are segmented (e.g., daily files) and standardized to 100 Hz. Waveforms are bandpass filtered in memory.
2. **ML Picking**: PhaseNet runs across continuous multi-station streams. Picks exceeding a probability threshold (e.g., $P \ge 0.3$ or $0.5$) are retained with timestamps and amplitudes.
3. **Phase Association via REAL (*Rapid Earthquake Association and Location*)**:
   - Searches a grid of candidate epicenters, depths, and origin times.
   - For a candidate grid point $(x_k, y_k, z_k)$ and origin time $t_{0}$, predicted travel times $t_P, t_S$ are computed using a 1D crustal velocity model.
   - Picks are associated when the residual $|t_{\text{obs}} - (t_0 + t_{\text{calc}})| \le \Delta t_{\text{threshold}}$.
   - Requires a minimum number of associated stations (e.g., $\ge 3$ or $4$) and phases to validate an event.
4. **Velocity Model Optimization & Absolute Location**:
   - **VELEST**: Simultaneously derives minimum 1D velocity models and station corrections (delay times) from initial associated picks.
   - **HYPOINVERSE**: Solves the linearized Geiger's equation using singular value decomposition (SVD) to produce formal hypocentral coordinates and origin times.
5. **Double-Difference Relocation (hypoDD / GrowClust)**:
   - Waveform cross-correlation calculates differential travel times among neighboring event pairs:
     $$(t_k^i - t_k^j)_{\text{obs}} - (t_k^i - t_k^j)_{\text{calc}} = \Delta m^i - \Delta m^j$$
   - Minimizes errors caused by unmodeled 3D velocity heterogeneities along common ray paths, sharpening fault geometries.

---

## 4. Earthquake Magnitude Estimation

Determining earthquake magnitude is a core deliverable of Work Package 5.1.1. In seismological practice and recent ML literature, two main strategies exist:

### 4.1 Classical Parametric & Amplitude-Based Formulation
The standard Richter/local magnitude $M_L$ equation is:
$$M_L = \log_{10}(A) - \log_{10}(A_0(\Delta)) + C_s$$
where:
- $A$ is the maximum horizontal ground displacement (or simulated Wood-Anderson response amplitude in millimeters).
- $-\log_{10}(A_0(\Delta))$ is the distance correction function for hypocentral distance $\Delta$.
- $C_s$ is the station calibration correction.

*Operational constraint identified in LOC-FLOW*: Instrument response deconvolution (converting raw counts to physical ground displacement/velocity) is required for rigorous $M_L$ computation. In the absence of response files for `VN.4001`–`4020`, temporary alternatives include:
1. **Signal Duration Magnitude ($M_D$)**:
   $$M_D = a_1 + a_2 \log_{10}(\tau) + a_3 \Delta$$
   where $\tau$ is the signal coda duration (from $P$-onset to the point where amplitude returns to the pre-event noise floor). Coda duration is scale-invariant with respect to instrument gain.
2. **Empirical Count-Based Proxy**: Fitting an empirical attenuation relationship directly against raw maximum peak ground velocity (PGV) counts when reference catalog magnitudes are available.

### 4.2 Deep Learning Direct Magnitude Regression
Recent methods reviewed in Xie (McGill) and Münchmeyer et al. (2021) formulate magnitude prediction as a direct regression problem from multi-station waveform envelopes or spectrograms:
$$\hat{M} = f_{\theta}(\mathbf{W}_1, \mathbf{W}_2, \dots, \mathbf{W}_N)$$
- Uses 1D CNNs or Transformer networks.
- Learns low-frequency spectral and amplitude saturation features without requiring manual phase picking or Wood-Anderson simulation.

---

## 5. Interface with Work Packages 5.1.2 and 6

### 5.1 Connection to Work Package 5.1.2: Ground Shaking Prediction
*Source: Khosravikia & Clayton (2021)*

Work Package 5.1.2 predicts ground motion intensity measures (Peak Ground Acceleration, PGA; Pseudo-Spectral Acceleration, PSA) across Northwest Vietnam.
- **Input Dependencies**: Directly consumes the parameters produced by 5.1.1:
  $$\mathbf{X} = \{M, R_{\text{hypo}}, z, V_{s30}\}$$
  where $M$ is magnitude, $R_{\text{hypo}} = \sqrt{R_{\text{epi}}^2 + z^2}$ is hypocentral distance, $z$ is focal depth, and $V_{s30}$ is time-averaged shear-wave velocity in the top 30 m.
- **Machine Learning Surrogates**: Khosravikia & Clayton demonstrate that Artificial Neural Networks (ANN), Random Forests (RF), and Support Vector Machines (SVM) outperform empirical Ground Motion Prediction Equations (GMPEs) in capturing nonlinear attenuation and near-source saturation.
- **Aleatory Uncertainty Quantification**: The model implements mixed-effects terms to decompose residuals into between-event variability ($\delta B_e$) and within-event site variability ($\delta W_{es}$):
  $$\ln(\text{PGA})_{ij} = f_{\text{ML}}(\mathbf{X}_{ij}) + \delta B_i + \delta W_{ij}$$

### 5.2 Deep Learning Paradigms in Earthquake Engineering
*Sources: Xie et al. (2020), Xie (McGill)*

The review papers emphasize:
1. **Transfer Learning**: When local seismic catalogs in target regions (Sơn La, Điện Biên, Lai Châu) contain limited large-magnitude recordings, models should be pre-trained on expansive global benchmarks (e.g., STEAD, INSTANCE, NCEDC) and fine-tuned using local waveform data.
2. **Physics-Informed Priors**: Embedding physical velocity bounds and causal travel-time constraints into loss functions to prevent unphysical hypocenter solutions.

### 5.3 Connection to Work Package 6: Urban Seismic Risk in Vietnam
*Source: Hanoi Urban Seismic Risk Study (2025)*

Work Package 6 addresses decision support and damage reduction. The Hanoi study provides the local domain baseline:
- Adapts HAZUS-MH damage functions specifically to Vietnamese building inventories (distinguishing non-engineered masonry and reinforced concrete frame structures).
- Incorporates diurnal population exposure models (daytime vs. nighttime casualty variation).
- Establishes the pipeline connecting:
  $$\text{Parameters (5.1.1)} \longrightarrow \text{PGA / ShakeMap (5.1.2)} \longrightarrow \text{Building Fragility \& Casualties (WP 6)}$$

---

## 6. Actionable Implementation Roadmap for Work Package 5.1.1

Based on the surveyed literature and current repository state:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Milestone 1: PhaseNet Model Pipeline Setup                                  │
│ - Load pre-trained PhaseNet weights (PyTorch).                              │
│ - Build stream inference pipeline on data/samples/4.0 MiniSEED files.       │
│ - Validate P/S pick probabilities and timestamp extraction.                 │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Milestone 2: Waveform Preprocessing & Discontinuity Handling                │
│ - Integrate with 511/inventory.py to filter and handle gaps/overlaps.       │
│ - Implement streaming sliding window (30 s, 100 Hz, 3-component).           │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Milestone 3: Phase Association (REAL / PyOcto)                              │
│ - Define spatial-temporal grid for Northwest Vietnam (20.5°-23.0°N,         │
│   102.5°-104.5°E).                                                          │
│ - Associate multi-station picks from VN.4001–4020 into candidate events.   │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Milestone 4: Regional 1D Crustal Velocity Model & Hypocenter Inversion      │
│ - Define initial 1D velocity structure for Northwest Vietnam crust.         │
│ - Implement hypocenter location solver (T₀, lat, lon, depth).               │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Milestone 5: Magnitude Estimation Module                                    │
│ - Implement duration magnitude (M_D) or empirical peak-count proxy.         │
│ - Prepare Wood-Anderson / M_L pipeline ready for calibration response data.│
└─────────────────────────────────────────────────────────────────────────────┘
```
