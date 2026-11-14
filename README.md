Introduction
======================

This is the main repository for VAST-Earthquake 4.0 project. 
Full project description is located in ```docs/proposal.pdf```.


Goals
======================

We have to implement the system in the work package 5, titled "Nghiên cứu xây dựng hệ thống tự động đánh giá rủi ro động đất ứng dụng trí tuệ nhân tạo cho các thành phố lớn khu vực Tây Bắc (TP. Sơn La, Tp. Điện Biên, Tp. Lai Châu), Việt Nam."

This work package is further split into smaller subworkpackages (SWP):
- 5.1.1: Nghiên cứu ứng dụng mô hình học máy, học sâu xác định các tham số động đất (độ lớn, độ sâu chấn tiêu…)
- 5.1.2: Nghiên cứu đánh giá khả năng rung động nền đất bằng mô hình học máy, học sâu cho các thành phố lớn khu vực Tây Bắc, Việt Nam

Additionally, we have to implement in another system in work package 6, titled "Xây dựng hệ thống hỗ trợ ra quyết định ứng phó, giảm thiểu thiệt hại do động đất cho khu vực thành phố lớn tại khu vực Tây Bắc (TP. Sơn La, Tp. Điện Biên, Tp. Lai Châu), Việt Nam"


Work package 5
====================

## 5.1.1
We are going to build, train, and evaluate machine learning, deep learning models for estimation of earthquake parameters from sensors data around the world.
Source code for this work package should be located in ```./511/``` folder.
See [511/README.md](511/README.md) for setup, waveform inspection, and the initial research sequence.

## 5.1.2
We are going to build, train, and evaluate machine learning, deep learning models for estimation of soil vibration (PGA, PSA).
Source code for this work package should be located in ```./512/``` folder.
See [512/README.md](512/README.md): open-data flatfile (USGS ShakeMap / NGA-West2), GMPE baseline vs. ML models, scenario shaking maps for the three cities.

Work package 6
====================

To be updated.



## Integration

We then build a full stack system to integrate these models for earthquake risk assessment. All source code must be located in ```./vasteq/```
- Frontend: Vanilla HTML/JS/CSS/Bootstrap
- Backend: Quarkus, Java
- Storage: MySQL
- Models: The models trained and evaluated on subworkpackages 5.1.1 and 5.1.2, served using FastAPI.

The following functionalities are required
- Authentication, using JWT
- User management, with 3 roles: admin, user, guest
- WebGIS to visualize the sensors location, information, collected data, seismic activities estimation. North-West Vietnam is the region of interest.
- Enter model parameters, launch model, visualize info.


References
======================

Reference papers for machine learning, deep learning models are located in ```./refs``` folder


Data
======================

Data sample is located in ```./data/samples``` folder.


Extra coding guidelines
======================

- All machine learning, deep learning models are going using numpy, scikit, pytorch.
- We can train models locally. Create virtual environments for training and evaluation experiments.
- In each work package, don't duplicate the data available in ```./data/```


