# 好みカルテ

チャンネル主の好みを 1 人 1 ファイル（`<人>.json`）で残す。`python -m backend.program_package.taste report --karte <人>` が
二択の答えから **未確認** の行を足す。本人が「そう」と押した行だけを決まりとして使い、「違う」の行は使わない。
AI が そう にすることはない。手順はスキル `taste-picker`。
