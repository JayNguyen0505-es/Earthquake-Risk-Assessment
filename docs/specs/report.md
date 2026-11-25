# Spec: results tables, figures and REPORT.md (phase G)

## 1. results/make_tables.py (reproducible; rerun whenever outputs change)
Inputs (Mac copies): 511/outputs/calibration_final/** (summary_by_k.csv, summary_by_k_ci.csv, info.json,
curve.csv, n_needed.csv, shaking/exceedance_summary.csv), 511/outputs/ablation/{old,m15}/**/summary/ablation_events.csv,
511/outputs/magnitude_meta/*/metrics.json and training_history.csv. Missing inputs -> skip that table, print a note.
Write results/tables/*.csv and a markdown version of each, and results/figures/*.png:
- T1 data: per region/model n test events, n station rows (from info.json n_test_events and tables), label type ML only.
- T2 checkpoint artefact: event MAE, bias, slope for old (AQ2009GM full) vs m15 (AQ2009GM_M1.5_snr10) checkpoints,
  auto_auto config, central_italy and ridgecrest; plus ref_analyst vs auto_auto for old (location/P effect).
- T3 in-domain (AQ2009GM_gauss/indomain): coverage and mean width by k (2,3,5,10,all), random mode, methods
  naive, naive_conf_bc, const_mondrian_bc, shared_gauss, shared_conf, with bootstrap CI columns if available.
  Also fitted tau, scale, ICC from info.json.
- T4 transfer N=0: coverage at k=2 and all for every region (transfer_<region>), same methods.
- T5 local-data curve: for each region, coverage_mean and interval_score_mean at N=0,10,20,30,50,100 for
  const_mondrian_bc vs shared_conf, k=2,3,all, scheme target_only (N=0 = source_only); and n_needed.csv rows.
  Relative interval-score gain of shared_conf vs const_mondrian_bc at N=30.
- T6 one-sided vs random dropout (mode column) for transfer/curve outputs where available.
- T7 classical ML (calibration_final/ml): temporal and curve results, same layout.
- T8 BSSA14: Brier, brier_ref and missed_hazard at threshold 0.1 g, Ms=5, k=all, transfer vs fewshot30 per region.
- T9 event-loss vs gaussian training: from magnitude_meta/AQ2009GM_{gauss,event}/metrics.json and training_history
  (dev RMSE, tau, event coverage). If InstanceGM_gauss exists, add its in-domain and transfer rows everywhere.
Figures: F1 coverage vs k in-domain; F2 local-data curves (coverage and interval score vs N, one panel per region,
k=2 and all); F3 BSSA14 missed-hazard bars N=0 vs N=30; F4 checkpoint artefact scatter-free bar (slope by checkpoint).
Use matplotlib, colour-blind safe palette, readable labels.

## 2. results/REPORT.md (Vietnamese, clear for an ICT reader new to seismology)
Sections: Tóm tắt (5 câu); Câu hỏi nghiên cứu; Dữ liệu (bảng T1); Phương pháp (ngắn: mô hình sai số chung,
conformal, các baseline, bớt trạm, đường cong dữ liệu địa phương, BSSA14); Kết quả A-F (mỗi mục: số liệu từ bảng +
1-2 câu diễn giải, dẫn tên file bảng/hình); Kết quả âm và sửa sai (checkpoint artefact: slope 0.3 cũ là do chọn nhầm
checkpoint M1.5; loss event khi train làm hỏng dự đoán điểm; Marche fewshot30 xấu hơn); Hạn chế (nhãn ML catalogue có sai số;
chuỗi ngắn 48h; vùng ít; BSSA14 ngoại suy; mô hình DL tự cài); Đánh giá khả năng công bố (trung thực: đóng góp chính là
đánh giá + đường cong N; lợi ích phương pháp nhỏ 6-17% ở k nhỏ) và venue phù hợp; Việc tiếp theo.
EVERY number in REPORT.md must be read from results/tables (write it via a small templating step in make_tables.py or
copy carefully); no invented numbers. Mark the InstanceGM section "đang chạy" if its outputs are missing.

## Rules
Use .venv-mac. Do not modify 511/ or 512/ code. Do not commit. Append one line to HANDOFF_STATE.md when done.
