"""使用本机 Android SDK 构建 APK，无 Gradle、无网络依赖。"""
from pathlib import Path
import os
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent
sdk = Path(os.environ.get('ANDROID_SDK_ROOT', r'C:\Program Files (x86)\Android\android-sdk'))
jdk = Path(os.environ.get('JAVA_HOME', r'C:\Program Files\Android\openjdk\jdk-21.0.8'))
tools = sdk/'build-tools/36.0.0'
android = sdk/'platforms/android-35/android.jar'
build = ROOT/'build'
classes = build/'classes'
classes.mkdir(parents=True, exist_ok=True)
# 清理本项目的旧字节码，避免已删除的 USB 相机内部类混入新版安装包。
for old in classes.rglob('*.class'):
    if not old.resolve().is_relative_to(classes.resolve()): raise RuntimeError('构建路径越界')
    old.unlink()


def run(args):
    subprocess.run([str(a) for a in args], check=True, cwd=ROOT)


run([tools/'aapt.exe', 'package', '-f', '-M', ROOT/'AndroidManifest.xml', '-I', android, '-F', build/'base.apk'])
run([jdk/'bin/javac.exe', '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-bootclasspath', str(android)+os.pathsep+str(tools/'core-lambda-stubs.jar'),
     '-d', classes, *ROOT.glob('src/**/*.java')])
class_jar = build/'classes.jar'
with zipfile.ZipFile(class_jar, 'w') as archive:
    for p in classes.rglob('*.class'): archive.write(p, p.relative_to(classes).as_posix())
run([jdk/'bin/java.exe', '-cp', tools/'lib/d8.jar', 'com.android.tools.r8.D8', '--min-api', '26',
     '--lib', android, '--output', build, class_jar])
with zipfile.ZipFile(build/'base.apk', 'a') as archive: archive.write(build/'classes.dex','classes.dex')
run([tools/'zipalign.exe','-f','4',build/'base.apk',build/'aligned.apk'])
key = build/'competition.keystore'
if not key.exists():
    run([jdk/'bin/keytool.exe','-genkeypair','-keystore',key,'-storepass','android','-keypass','android',
         '-alias','competition','-keyalg','RSA','-keysize','2048','-validity','3650',
         '-dname','CN=LabGuard Competition, O=Local Demo, C=CN'])
output = ROOT/'LabGuard-Pocket.apk'
run([jdk/'bin/java.exe','-jar',tools/'lib/apksigner.jar','sign','--ks',key,'--ks-pass','pass:android',
     '--ks-key-alias','competition','--out',output,build/'aligned.apk'])
run([jdk/'bin/java.exe','-jar',tools/'lib/apksigner.jar','verify','--verbose',output])
print('APK:',output)
