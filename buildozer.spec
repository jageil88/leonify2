[app]
title = Leonify
package.name = leonify
package.domain = com.leon
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 4.0
requirements = python3,kivy==2.3.0
orientation = portrait
fullscreen = 0
android.permissions = READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_AUDIO
android.api = 33
android.minapi = 24
android.ndk = 25b
android.ndk_api = 24
android.archs = arm64-v8a
android.allow_backup = True
android.accept_sdk_license = True
android.release_artifact = apk

[buildozer]
log_level = 2
warn_on_root = 1
