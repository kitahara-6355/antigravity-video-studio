# 顔検出のモデル

`face_detection_yunet_2023mar.onnx`（232,589 バイト・md5 `4ae92eeb150c82ce15ac80738b3b8167`）

- 出所: OpenCV Zoo の YuNet（https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet ）
- ライセンス: MIT（Copyright (c) 2020 Shiqi Yu）
- 使う所: `backend/program_package/vision.py`（`cv2.FaceDetectorYN`）。CPU で動く。課金なし
- 取得日: 2026-11-10

# 表情のモデル

`facial_expression_recognition_mobilefacenet_2022july.onnx`（4,791,892 バイト・md5 `0c6cf217e1efdd7e7ec436831a932451`）

- 出所: OpenCV Zoo の表情認識（https://github.com/opencv/opencv_zoo/tree/main/models/facial_expression_recognition ）
- ライセンス: Apache 2.0
- 出力は7種（angry・disgust・fearful・happy・neutral・sad・surprised）。index 3 が笑顔
- 使う所: `backend/program_package/vision.py` の `Expr`（`scan --expr`）。YuNet の5点で顔を 112x112 にそろえてから入れる。CPU で動く。課金なし
- 取得日: 2026-11-15
