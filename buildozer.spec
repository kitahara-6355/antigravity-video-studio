[app]

# (str) Title of your application
title = Video Automation Studio

# (str) Package name
package.name = video_automation_studio

# (str) Package domain (needed for android packaging)
package.domain = com.antigravity

# (str) Source code directory
source.dir = .

# (list) Source files to include (let empty to include all the files)
source.include_exts = py,png,jpg,kv,html,css,js,json,txt,spec

# (list) List of exclusions using pattern matching
source.exclude_patterns = tests/*, bin/*.exe, *.spec, .git/*, .pytest_cache/*, .agent/*

# (list) Application requirements
# comma separated e.g. requirements = sqlite3,kivy
requirements = python3,kivy,requests,urllib3,psutil

# (str) Custom source folders for requirements
# It may be necessary to add custom libraries or binary dependencies.

# (list) Permissions
android.permissions = INTERNET, READ_EXTERNAL_STORAGE, WRITE_EXTERNAL_STORAGE

# (int) Target Android API, should be as high as possible.
android.api = 33

# (int) Minimum API your APK will support.
android.minapi = 21

# (list) The Android archs to build for, choices: armeabi-v7a, arm64-v8a, x86, x86_64
android.archs = arm64-v8a

# (bool) Use --private data directory (True) or shared directory (False)
android.private_storage = True

# (list) Android additionnal libraries to copy into libs/armeabi
# Android用FFmpegバイナリなどをアプリパッケージに同梱するための設定
# android.add_libs_armeabi = libs/armeabi-v7a/libffmpeg.so
