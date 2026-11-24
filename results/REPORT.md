# Bất định của độ lớn động đất khi ít trạm và khi chuyển vùng

## Tóm tắt

Báo cáo đo độ tin cậy của khoảng dự đoán độ lớn địa phương khi giảm số trạm hoặc đem mô hình sang một vùng mới. Trên AQ2009GM cùng miền, khoảng danh định 95% theo giả định trạm độc lập chỉ bao phủ 52,9% sự kiện khi dùng toàn bộ trạm, còn hiệu chuẩn có thành phần sai số chung đạt 94,2%. Khi chuyển vùng và chưa dùng sự kiện địa phương, độ phủ của phương pháp sai số chung kết hợp conformal chỉ đạt 10,6–76,8% với toàn bộ trạm. Với 30 sự kiện địa phương và giữ ngẫu nhiên 2 trạm, phương pháp này giảm điểm phạt của khoảng dự đoán 5,1–17,1% so với baseline độ rộng cố định theo số trạm. Trong mô phỏng rung lắc ở Central Italy, tỷ lệ bỏ sót nguy cơ giảm từ 9,60% xuống 0,06% sau hiệu chuẩn địa phương, còn điểm Brier tại Marche tăng.

## Câu hỏi nghiên cứu

- Giả định các trạm độc lập làm khoảng dự đoán quá hẹp đến mức nào khi số trạm thay đổi? Độ dốc dự đoán thấp đến từ đâu?
- Khi chuyển vùng, cần bao nhiêu sự kiện đã biết độ lớn địa phương để lấy lại độ phủ? Thành phần sai số chung cải thiện điểm khoảng bao nhiêu so với baseline đã hiệu chỉnh thiên lệch?
- Hiệu chuẩn độ lớn thay đổi xác suất vượt ngưỡng rung lắc trong mô phỏng ra sao?

## Dữ liệu

Nhãn tham chiếu là độ lớn địa phương ML từ danh mục động đất. DL là mô hình học sâu đọc dạng sóng. ML cổ điển ở cột mô hình là cách tính độ lớn địa phương từ biên độ và khoảng cách, với hiệu chỉnh trạm trong lượt hiệu chuẩn theo thời gian. HN là cấu hình chỉ dùng kênh gia tốc HN của Central Italy. Hai cấu hình Central Italy dùng chung danh mục sự kiện.

| Mô hình | Miền kiểm thử | Thiết lập | Nhãn | Sự kiện | Dòng trạm |
| --- | --- | --- | --- | ---: | ---: |
| AQ2009GM_gauss | AQ2009GM | Cùng miền | ML | 6324 | 125060 |
| AQ2009GM_gauss | Central Italy | Chuyển vùng | ML | 706 | 13414 |
| AQ2009GM_gauss | Central Italy (HN) | Chuyển vùng | ML | 706 | 11295 |
| AQ2009GM_gauss | Marche | Chuyển vùng | ML | 293 | 5682 |
| AQ2009GM_gauss | Ridgecrest | Chuyển vùng | ML | 1442 | 25239 |
| ML cổ điển | Central Italy | Chia theo thời gian | ML | 353 | 6707 |
| ML cổ điển | Central Italy (HN) | Chia theo thời gian | ML | 353 | 5648 |
| ML cổ điển | Marche | Chia theo thời gian | ML | 147 | 2909 |
| ML cổ điển | Ridgecrest | Chia theo thời gian | ML | 721 | 12888 |

Mỗi dòng trạm là một bản ghi của một sự kiện tại một trạm. Số liệu được đếm từ các hàng dùng toàn bộ trạm trong tập kiểm thử. Các tập kiểm thử sau khi dành sự kiện cho hiệu chuẩn few-shot cũng có trong bảng. [T1_data.md](tables/T1_data.md)

### InstanceGM — đang chạy

Bản sao trên Mac chưa có kết quả InstanceGM. Các nhận định bên dưới dựa trên AQ2009GM và ML cổ điển.

## Phương pháp

- **Sai số chung giữa các trạm.** Với cùng một động đất, phần sai số chung có độ lệch chuẩn τ. Phần riêng của trạm dùng độ bất định mô hình sau khi nhân hệ số scale. Thêm trạm giúp giảm phần sai số riêng, còn phần chung vẫn tồn tại. `shared_gauss` dùng trực tiếp khoảng Gaussian, còn `shared_conf` dùng phân vị conformal của sai số đã chuẩn hóa trên tập hiệu chuẩn.
- **Baseline.** `naive` giả định sai số các trạm độc lập. `naive_conf_bc` trừ thiên lệch ước lượng trên dữ liệu hiệu chuẩn rồi nhân độ rộng với một hệ số chung. `const_mondrian_bc` cũng trừ thiên lệch và học một độ rộng cố định cho mỗi giá trị k. Độ phủ là tỷ lệ khoảng chứa nhãn danh mục. Điểm khoảng phạt cả độ rộng lẫn mức nhãn rơi ra ngoài khoảng, nên thấp hơn là tốt hơn.
- **Bớt trạm và dữ liệu địa phương.** Giữ k = 2, 3, 5, 10 hoặc toàn bộ trạm. Hai cách chọn là ngẫu nhiên và chỉ giữ trạm về một phía của tâm chấn. Bảng chính dùng chọn ngẫu nhiên ở k hữu hạn. Đường cong thay đổi số sự kiện hiệu chuẩn N lấy từ phần đầu của chuỗi đích rồi kiểm thử trên phần sau. N = 0 dùng hiệu chuẩn nguồn, còn N dương trong đường cong chính chỉ dùng dữ liệu đích. Khoảng tin cậy trong bảng độ phủ lấy bootstrap theo sự kiện.
- **Rung lắc.** Mô hình BSSA14 chuyển độ lớn và độ bất định của nó thành xác suất gia tốc nền cực đại (PGA) vượt ngưỡng. Bài thử đưa sai số độ lớn đã quan sát vào một kịch bản giả lập. Điểm Brier đo sai số xác suất so với các lần mô phỏng vượt ngưỡng, còn `brier_ref` dùng xác suất tính từ độ lớn tham chiếu. Chỉ số bỏ sót nguy cơ đếm các trường hợp xác suất dự đoán thấp trong khi xác suất tham chiếu cao. [T3_indomain.md](tables/T3_indomain.md) · [T5_curve.md](tables/T5_curve.md) · [T8_bssa14.md](tables/T8_bssa14.md)

## Kết quả A–F

### A. Co độ lớn và ảnh hưởng của checkpoint

Với vị trí và thời điểm đến của sóng P lấy tự động (`auto_auto`), độ dốc dự đoán theo nhãn tại Central Italy và Ridgecrest là 0,875 và 0,701 với checkpoint AQ2009GM đầy đủ, rồi giảm còn 0,304 và 0,291 với checkpoint M1.5. Khi dùng vị trí tham chiếu và sóng P do chuyên viên đánh dấu (`ref_analyst`) với checkpoint đầy đủ, độ dốc lần lượt là 0,827 và 0,695. So sánh hai checkpoint trong cùng cấu hình tái hiện độ co mạnh. Phép so vị trí và P gộp hai thay đổi và có số sự kiện khác nhau giữa cấu hình. [T2_checkpoint.md](tables/T2_checkpoint.md) · [F4_checkpoint_slope.png](figures/F4_checkpoint_slope.png)

### B. Dữ liệu vùng đích và ML cổ điển

Khi hiệu chuẩn trên phần đầu của từng chuỗi và dùng toàn bộ trạm, ML cổ điển với `shared_conf` đạt độ phủ 96,0% tại Central Italy, 96,6% với HN, 96,0% tại Ridgecrest và 87,1% tại Marche. Trên đường cong ML cổ điển của Marche, ở N = 30 và k = 2, điểm khoảng của `shared_conf` là 2,159 so với 1,994 của baseline. Chênh lệch này cho thấy lợi ích của thành phần sai số chung phụ thuộc vào bộ ước lượng và chuỗi kiểm thử. [T7_temporal.md](tables/T7_temporal.md) · [T7_curve.md](tables/T7_curve.md) · [T7_gain.md](tables/T7_gain.md) · [T7_n_needed.md](tables/T7_n_needed.md)

### C. Hàm mất mát khi huấn luyện

Gaussian và event loss lần lượt cho RMSE độ lớn theo sự kiện là 0,173 và 0,423 trên tập kiểm thử, với RMSE tập phát triển ở epoch cuối là 0,189 và 0,470. Event loss học τ = 0,416 và đạt độ phủ 95,4% khi dùng phương sai chung. Trong lượt huấn luyện này, độ phủ cao đi kèm dự đoán điểm kém, nên phần đánh giá chuyển vùng bên dưới sử dụng mô hình Gaussian. [T9_training.md](tables/T9_training.md) · [T9_history.md](tables/T9_history.md)

### D. Hiệu chuẩn cùng miền và hình học mạng trạm

Trên AQ2009GM, `naive` giảm độ phủ từ 91,0% ở k = 2 xuống 52,9% ở k = all, cùng lúc độ rộng trung bình giảm từ 0,494 xuống 0,166 đơn vị độ lớn. Ở k = all, `shared_conf` đạt 94,2% (CI 93,6–94,8%) và baseline Mondrian đạt 94,7% (CI 94,1–95,2%). Ước lượng τ = 0,165, scale = 0,473 và tương quan nội lớp trên tập kiểm thử là 0,660, phù hợp với hiện tượng trạm cùng sự kiện có sai số tương quan. Khi chuyển sang Ridgecrest ở k = 2, `shared_conf` đạt 63,4% nếu giữ trạm ngẫu nhiên và 61,6% nếu chỉ giữ trạm một phía. So sánh hai kiểu bớt trạm cần xét cả số sự kiện đủ trạm cho mỗi kiểu, nhất là ở k lớn. [T3_indomain.md](tables/T3_indomain.md) · [T3_fit.md](tables/T3_fit.md) · [T6_transfer.md](tables/T6_transfer.md) · [T6_curve.md](tables/T6_curve.md) · [F1_coverage_vs_k.png](figures/F1_coverage_vs_k.png)

### E. Chuyển vùng và số sự kiện cần để hiệu chuẩn

Không có sự kiện địa phương, `shared_conf` dùng toàn bộ trạm đạt độ phủ 10,6% ở Central Italy, 32,3% ở cấu hình HN, 76,8% ở Marche và 65,3% ở Ridgecrest. Với N = 30 và k = 2, độ phủ trung bình của phương pháp này lên 93,4–96,5%, với điểm khoảng thấp hơn baseline 5,1–17,1%. Bảng `n_needed` lấy N nhỏ nhất đạt ngưỡng của phép thử sau khi gộp các kiểu bớt trạm. Với `shared_conf`, mốc này là 10–20 sự kiện tại k = 2 và 20–200 sự kiện khi dùng toàn bộ trạm, tùy tập đích. Vì vậy, mốc hữu ích cho mạng thưa trong các chuỗi đã thử có thể thay đổi khi đổi vùng hoặc số trạm. [T4_transfer.md](tables/T4_transfer.md) · [T5_curve.md](tables/T5_curve.md) · [T5_gain.md](tables/T5_gain.md) · [T5_n_needed.md](tables/T5_n_needed.md) · [F2_local_data.png](figures/F2_local_data.png)

### F. Kiểm tra hệ quả đối với rung lắc

Trong kịch bản Mₛ = 5, ngưỡng PGA 0,1 g và dùng toàn bộ trạm, `shared_conf` ở Central Italy giảm tỷ lệ bỏ sót nguy cơ từ 9,60% xuống 0,06% và điểm Brier từ 0,169 xuống 0,123, với Brier tham chiếu khoảng 0,112. Sau hiệu chuẩn địa phương, điểm Brier của baseline Mondrian là 0,122. Cấu hình few-shot dành các sự kiện đầu cho hiệu chuẩn nên hai lượt mô phỏng có số ca kiểm thử khác nhau. [T8_bssa14.md](tables/T8_bssa14.md) · [F3_missed_hazard.png](figures/F3_missed_hazard.png)

## Kết quả âm và sửa sai

- **Checkpoint.** Độ dốc cũ xấp xỉ 0,3 là do chọn nhầm checkpoint M1.5 trong lần chạy cũ. Chạy lại cùng cấu hình tự động tái hiện con số đó ở cả hai vùng. Checkpoint đầy đủ vẫn cho độ dốc thấp hơn mức lý tưởng và có thiên lệch âm. [T2_checkpoint.md](tables/T2_checkpoint.md)
- **Event loss.** Độ phủ cao của khoảng có thành phần sai số chung đi kèm RMSE lớn hơn hẳn. Cần kiểm tra chất lượng dự đoán điểm cùng với độ phủ khi đánh giá hàm mất mát. [T9_training.md](tables/T9_training.md)
- **Marche few-shot.** Sau khi hiệu chuẩn bằng 30 sự kiện đầu, điểm Brier của `shared_conf` tăng từ 0,130 lên 0,143, dù tỷ lệ bỏ sót nguy cơ giảm. Biến động thiên lệch trong chuỗi là một cách giải thích cần được kiểm tra trên cùng tập kiểm thử. [T8_bssa14.md](tables/T8_bssa14.md)

## Hạn chế

Nhãn ML của danh mục có sai số và có thể lệch theo vùng. Các chuỗi kiểm thử chuyển vùng chỉ kéo dài khoảng 41–48 giờ, số vùng ít, và hai cấu hình Central Italy cùng đại diện cho một vùng địa lý. BSSA14 được dùng ở đây để ngoại suy trong mô phỏng, với độ lớn danh mục ML khác thang độ lớn mô men Mw mà mô hình rung lắc sử dụng. Kết quả phụ thuộc vào mô hình DL tự cài và hiện chưa có đối chứng InstanceGM trong bản sao kết quả. [T1_data.md](tables/T1_data.md) · [T8_bssa14.md](tables/T8_bssa14.md)

## Đánh giá khả năng công bố

Đóng góp chính là định lượng mức quá tự tin khi thay đổi số trạm và đo số sự kiện địa phương cần để phục hồi độ phủ. Lợi ích của phương pháp ở k = 2 là khiêm tốn và thay đổi giữa các tập đích, với mức giảm điểm khoảng 5,1–17,1% so với một baseline mạnh tại N = 30. Kết quả phù hợp với một bài đánh giá thực nghiệm tập trung cho *Seismological Research Letters*, sau khi kiểm tra thêm độ lặp lại trên chuỗi và mô hình độc lập. [T5_gain.md](tables/T5_gain.md) · [Hướng dẫn tác giả của SRL](https://www.seismosoc.org/publications/srl-authorsinfo-2/)

## Việc tiếp theo

- Bổ sung InstanceGM và lặp lại so sánh trên chuỗi dài hơn ở các vùng độc lập.
- Đo khoảng tin cậy cho chênh lệch điểm khoảng giữa các phương pháp trên cùng sự kiện. Kiểm tra độ ổn định của đường cong khi đổi mốc thời gian chia chuỗi.
- So sánh lại BSSA14 trên cùng tập sự kiện giữ lại ở cả hai chế độ hiệu chuẩn. Dùng tập con có cả ML và Mw để kiểm tra ảnh hưởng của thang độ lớn.
