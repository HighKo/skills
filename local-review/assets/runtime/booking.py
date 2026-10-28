#!/usr/bin/env python3
"""One reusable local booking stack. Run with --help for the supported actions."""
import argparse
import base64
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.parse

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
STATE = ROOT / 'state'
LOGS = ROOT / 'logs'
STACK = json.loads((ROOT / 'stack.json').read_text())
SERVICES = WORKSPACE / STACK['services']['path']
APP = WORKSPACE / STACK['app']['path']
PORTAL = WORKSPACE / STACK['portal']['path']
FLUTTER = Path.home() / '.cache/flutter_sdk/bin/flutter'
SDK = Path.home() / 'Android/Sdk'
ADB = SDK / 'platform-tools/adb'
DEVICE = 'emulator-5554'
DATABASE = 'chaanz_booking_local'
BUCKET = 'chaanz-booking-local'
PINS = {name: (WORKSPACE / item['path'], item['pr'], item['commit']) for name, item in STACK.items()}


def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def output(args, **kwargs):
    return subprocess.check_output([str(x) for x in args], text=True, **kwargs).strip()


def read_json(path, default=None):
    return json.loads(path.read_text()) if path.exists() else (default if default is not None else {})


def save(path, value):
    temporary = path.with_suffix('.new')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.chmod(0o600)
    temporary.replace(path)


def check_disk():
    free = shutil.disk_usage(WORKSPACE).free
    baseline = read_json(STATE / 'disk.json')
    if not baseline:
        baseline = {'free_bytes': free, 'recorded_at': time.time()}
        save(STATE / 'disk.json', baseline)
    growth = baseline['free_bytes'] - free
    if free < 20 * 1024**3 or growth > 10 * 1024**3:
        raise RuntimeError(f'Disk budget reached: {free/1024**3:.1f} GiB free, {growth/1024**3:.1f} GiB net growth')
    return f'{free/1024**3:.1f} GiB free; {growth/1024**3:.2f} GiB net growth since setup'


def verify_pins():
    manifest = {}
    for name, (path, pr, sha) in PINS.items():
        actual = output(['git', '-C', path, 'rev-parse', 'HEAD'])
        if actual != sha:
            raise RuntimeError(f'{name}: checkout moved from pinned PR revision; update/review manifest first')
        manifest[name] = {'path': str(path), 'pr': f'https://github.com/chaanzapp/{name}/pull/{pr}' if pr else None, 'ref': STACK[name].get('ref'), 'commit': sha}
    save(ROOT / 'revisions.json', manifest)


def dotenv(path):
    spec = importlib.util.spec_from_file_location('local_config', SERVICES / 'dev/configure.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.read_env(path)


def required_local_setting(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f'Set {name} in your local environment; credentials are not bundled')
    return value


def service_env(service):
    template = SERVICES / service / '.config/.env.development'
    env = {**os.environ, **(dotenv(template) if template.exists() else {})}
    local_url = required_local_setting('CHAANZ_LOCAL_DATABASE_URL')
    parsed = urllib.parse.urlsplit(local_url)
    if parsed.scheme not in ('postgres', 'postgresql') or parsed.hostname not in ('localhost', '127.0.0.1') or parsed.path != '/' + DATABASE:
        raise RuntimeError('Use the selected isolated review database on loopback')
    query = dict(urllib.parse.parse_qsl(parsed.query))
    query.pop('search_path', None)
    db = urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(query)))
    db += ('&' if query else '?') + 'search_path='
    env.update(DATABASE_URL=db + service + ',public', READ_DATABASE_URL=db + service + ',public',
               LOCALES_DIR='internal/l10n/locales', LAMBDA_MAILER_URL='http://127.0.0.1:8090/send',
               LAMBDA_PUSH_NOTIFICATION_SENDER_URL='http://log',
               GOPROXY='off', GOTOOLCHAIN='local', GOPRIVATE='github.com/chaanzapp',
               TMPDIR=str(ROOT / 'tmp'))
    if service == 'auth':
        env.update(HTTP_PORT='8081', BASE_PATH='auth', INTERNAL_BASE_PATH='internal-auth',
                   PLATFORM_INTERNAL_BASE_URL='http://127.0.0.1:8080/internal',
                   PORTAL_TEST_USER_EMAIL='disabled-local-test-user@example.test')
    elif service == 'platform':
        auth = dotenv(SERVICES / 'auth/.config/.env.development')
        env.update(HTTP_PORT='8080', APP_BASE_PATH='app', PORTAL_BASE_PATH='portal', ADMIN_BASE_PATH='admin',
                   INTERNAL_BASE_PATH='internal', STAFF_BASE_PATH='staff',
                   AUTH_INTERNAL_BASE_URL='http://127.0.0.1:8081/internal-auth',
                   MEDIA_DATABASE_URL=db + 'media,public', CDN_BASE_URL='http://127.0.0.1:8082',
                   PORTAL_URL='http://localhost:3000', PAGES_BASE_URL='http://127.0.0.1:8082/public',
                   AWS_S3_ACCESS_KEY_ID=required_local_setting('CHAANZ_LOCAL_S3_ACCESS_KEY_ID'), AWS_S3_SECRET_ACCESS_KEY=required_local_setting('CHAANZ_LOCAL_S3_SECRET_ACCESS_KEY'), AWS_S3_REGION='us-east-1',
                   AWS_S3_BUCKET=BUCKET, PUBLIC_MEDIA_DIR='public',
                   AWS_ENDPOINT_URL_S3='http://127.0.0.1:9090', AWS_S3_FORCE_PATH_STYLE='true')
        for kind in ('PLATFORM', 'PORTAL', 'ADMIN'):
            env[f'AUTH_{kind}_TOKEN_PUBLIC_KEY'] = auth[f'{kind}_TOKEN_PUBLIC_KEY']
    else:
        env.update(HTTP_PORT='8086', BASE_PATH='media', INTERNAL_ACCESS_TOKEN=required_local_setting('CHAANZ_LOCAL_MEDIA_ACCESS_TOKEN'),
                   AWS_ACCESS_KEY_ID=required_local_setting('CHAANZ_LOCAL_S3_ACCESS_KEY_ID'), AWS_SECRET_ACCESS_KEY=required_local_setting('CHAANZ_LOCAL_S3_SECRET_ACCESS_KEY'), AWS_REGION='us-east-1',
                   AWS_BUCKET=BUCKET, PUBLIC_MEDIA_DIR='public')
    return env


def sql(query, database=DATABASE):
    return output(['docker', 'exec', '-i', 'chaanz-dev-db', 'psql', '-U', 'chaanz', '-d', database,
                   '-v', 'ON_ERROR_STOP=1', '-At'], input=query)


def local_edit(path, transform):
    records = read_json(STATE / 'overrides.json')
    key = str(path.relative_to(WORKSPACE))
    text = path.read_text()
    if key in records:
        if hashlib.sha256(text.encode()).hexdigest() != records[key]['sha256']:
            raise RuntimeError(f'Local override edited since setup: {path}; refusing to overwrite')
        return
    original = ROOT / 'originals' / key
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_text(text)
    changed = transform(text)
    if changed == text:
        raise RuntimeError(f'Expected local override anchor not found: {path}')
    path.write_text(changed)
    records[key] = {'original': str(original.relative_to(ROOT)), 'sha256': hashlib.sha256(changed.encode()).hexdigest()}
    save(STATE / 'overrides.json', records)


def configure_portal_images():
    def patch(text):
        if text.count('const nextConfig = {') != 1 or text.count('  images: {') != 1 or text.count('    remotePatterns: [') != 1:
            raise RuntimeError('Portal image config changed; inspect the local override anchors')
        text = text.replace('const nextConfig = {',
            "// Local review only; production image policy stays unchanged.\n"
            "const localBookingImages = process.env.NODE_ENV === 'development' && process.env.CHAANZ_LOCAL_BOOKING === '1';\n"
            'const nextConfig = {', 1)
        text = text.replace('  images: {',
            '  images: {\n    dangerouslyAllowLocalIP: localBookingImages,', 1)
        return text.replace('    remotePatterns: [',
            "    remotePatterns: [\n      ...(localBookingImages ? [{ protocol: 'http', hostname: '127.0.0.1', port: '9090', pathname: '/" + BUCKET + "/public/**', search: '' }] : []),", 1)
    local_edit(PORTAL / 'next.config.js', patch)


def configure():
    verify_pins()
    configure_portal_images()
    auth = dotenv(SERVICES / 'auth/.config/.env.development')
    public_key = base64.b64decode(auth['PLATFORM_TOKEN_PUBLIC_KEY']).decode().strip()
    local_edit(APP / 'app_demo_highfield/lib/main.dart', lambda s: re.sub(
        r"jwtPublicKey = '''.*?''';", "jwtPublicKey = '''\n" + public_key + "\n''';", s, count=1, flags=re.S))
    local_edit(APP / 'base_app/lib/platform/model/platform.dart', lambda s: s.replace(
        'final host = "https://stage-api.v2.chaanz.com";', 'final host = "http://10.0.2.2:8082";', 1))
    local_edit(APP / 'app_demo_highfield/android/app/src/debug/AndroidManifest.xml', lambda s: s.replace(
        '</manifest>', '    <application android:usesCleartextTraffic="true" />\n</manifest>', 1))
    # Shared Gradle script configures release signing even during debug setup.
    signing = APP / 'app_demo_highfield/android/key.properties'
    if not signing.exists():
        shutil.copy2(Path(required_local_setting('CHAANZ_LOCAL_ANDROID_KEY_PROPERTIES')), signing)
        signing.chmod(0o600)
    # Flutter normally generates these files. Reuse its cached wrapper, adding
    # --offline so Gradle cannot silently fetch another Android dependency stack.
    wrapper_source = FLUTTER.parent / 'cache/artifacts/gradle_wrapper'
    android = APP / 'app_demo_highfield/android'
    wrapper = android / 'gradlew'
    if not wrapper.exists():
        wrapper.write_text((wrapper_source / 'gradlew').read_text().replace(
            'org.gradle.wrapper.GradleWrapperMain "$@"', 'org.gradle.wrapper.GradleWrapperMain --offline "$@"'))
        wrapper.chmod(0o755)
    elif 'org.gradle.wrapper.GradleWrapperMain --offline' not in wrapper.read_text():
        raise RuntimeError('Existing gradlew is not the local offline wrapper; inspect before changing it')
    jar = android / 'gradle/wrapper/gradle-wrapper.jar'
    if not jar.exists():
        shutil.copy2(wrapper_source / 'gradle/wrapper/gradle-wrapper.jar', jar)
    save(ROOT / 'Booking.code-workspace', {
        'folders': [{'name': name.title() + (' PR ' + str(item['pr']) if item.get('pr') else ' base'), 'path': str(WORKSPACE / item['path'])} for name, item in STACK.items()] + [{'name': 'Local runner', 'path': '.'}],
        'settings': {'dart.flutterSdkPath': str(FLUTTER.parent.parent)},
        'launch': {'version': '0.2.0', 'configurations': [{'name': 'Booking local — Highfield', 'type': 'dart',
                    'request': 'attach', 'cwd': str(APP / 'app_demo_highfield'),
                    'deviceId': DEVICE,
                    'env': {'ANDROID_HOME': str(SDK), 'ANDROID_SDK_ROOT': str(SDK)}}]}})


def build(service):
    print(f'Building {service} from pinned PR (cached Go dependencies only)…', flush=True)
    with (LOGS / f'build-{service}.log').open('w') as log:
        run(['go', 'build', '-buildvcs=false', '-o', ROOT / 'bin' / service, '.'], cwd=SERVICES / service,
            env=service_env(service), stdout=log, stderr=subprocess.STDOUT)
    check_disk()


def prepare():
    runtime = read_json(STATE / 'runtime.json', {'processes': {}})
    if any(alive(item) for item in runtime['processes'].values()):
        raise RuntimeError('Stop the local stack before preparing another revision')
    configure()
    for name in ('media', 'auth', 'platform'):
        build(name)
    dependencies = read_json(STATE / 'dependencies.json')
    portal_lock = hashlib.sha256((PORTAL / 'package-lock.json').read_bytes()).hexdigest()
    if dependencies.get('portal_lock') != portal_lock or not (PORTAL / 'node_modules/next/dist/bin/next').exists():
        print('Resolving portal dependencies from npm cache…', flush=True)
        with (LOGS / 'npm.log').open('w') as log:
            run(['npm', 'ci', '--offline', '--ignore-scripts', '--no-audit', '--no-fund'], cwd=PORTAL,
                stdout=log, stderr=subprocess.STDOUT)
        save(STATE / 'dependencies.json', {'portal_lock': portal_lock})
    check_disk()
    print('Resolving app dependencies from pub cache…', flush=True)
    with (LOGS / 'pub.log').open('w') as log:
        run([FLUTTER, 'pub', 'get', '--offline', '--enforce-lockfile'], cwd=APP / 'app_demo_highfield',
            stdout=log, stderr=subprocess.STDOUT)
    check_disk()
    save(STATE / 'prepared.json', {'at': time.time(), 'stack': STACK})


def process_stamp(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().split(') ', 1)[1].split()
        return None if fields[0] == 'Z' else fields[19]
    except (FileNotFoundError, ProcessLookupError):
        return None


def alive(item):
    return item['stamp'] is not None and process_stamp(item['pid']) == item['stamp']


def spawn(name, argv, cwd=ROOT, env=None):
    state = read_json(STATE / 'runtime.json', {'processes': {}, 'containers': []})
    if name in state['processes'] and alive(state['processes'][name]):
        return
    with (LOGS / (name + '.log')).open('ab') as log:
        proc = subprocess.Popen([str(x) for x in argv], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    state['processes'][name] = {'pid': proc.pid, 'stamp': process_stamp(proc.pid), 'command': [str(x) for x in argv]}
    save(STATE / 'runtime.json', state)


def wait_url(url, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status == 200:
                    return
        except (OSError, TimeoutError):
            pass
        time.sleep(1)
    raise RuntimeError(f'Not ready: {url}; inspect logs in {LOGS}')


def start_containers():
    for name in ('chaanz-dev-db', 'chaanz-dev-s3-1'):
        data = json.loads(output(['docker', 'inspect', name]))[0]
        if not data['State']['Running']:
            state = read_json(STATE / 'runtime.json', {'processes': {}, 'containers': []})
            if name not in state['containers']:
                state['containers'].append(name)
            save(STATE / 'runtime.json', state)
            run(['docker', 'start', name])
    for _ in range(60):
        result = subprocess.run(['docker', 'exec', 'chaanz-dev-db', 'pg_isready', '-U', 'chaanz'], capture_output=True)
        if result.returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError('Existing PostgreSQL container did not become ready')
    wait_url('http://127.0.0.1:9090/chaanz-dev-media/')
    req = urllib.request.Request(f'http://127.0.0.1:9090/{BUCKET}', method='PUT', data=b'')
    try:
        urllib.request.urlopen(req).close()
    except urllib.error.HTTPError as error:
        if error.code != 409:
            raise


def database_setup():
    if sql(f"SELECT 1 FROM pg_database WHERE datname='{DATABASE}'", 'postgres') != '1':
        sql(f'CREATE DATABASE {DATABASE}', 'postgres')
    sql('CREATE SCHEMA IF NOT EXISTS auth; CREATE SCHEMA IF NOT EXISTS platform; CREATE SCHEMA IF NOT EXISTS media;')
    for name in ('media', 'auth', 'platform'):
        with (LOGS / f'migrate-{name}.log').open('w') as log:
            run([ROOT / 'bin' / name, '--migrate'], cwd=SERVICES / name, env=service_env(name), stdout=log, stderr=subprocess.STDOUT)
    if sql('SELECT count(*) FROM auth.portal_auth_user') == '0':
        with (LOGS / 'seed-auth.log').open('w') as log:
            run([ROOT / 'bin/auth', '--testdata'], cwd=SERVICES / 'auth', env=service_env('auth'), stdout=log, stderr=subprocess.STDOUT)
    if sql('SELECT count(*) FROM platform.organizer') == '0':
        with (LOGS / 'seed-platform.log').open('w') as log:
            run([ROOT / 'bin/platform', '--testdata'], cwd=SERVICES / 'platform', env=service_env('platform'), stdout=log, stderr=subprocess.STDOUT)
    seed_file = ROOT / 'fixtures.sql'
    if seed_file.exists() and sql("SELECT to_regclass('public.booking_local_setup') IS NOT NULL") != 't':
        sql(seed_file.read_text())
        save(STATE / 'seeded.json', {'at': time.time(), 'database': DATABASE})


def check_ports(ports):
    for port in ports:
        with socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1', port))
            except OSError:
                raise RuntimeError(f'Port {port} is already in use; no process was replaced')


def emulator():
    if DEVICE not in output([ADB, 'devices']):
        spawn('emulator', [SDK / 'emulator/emulator', '-avd', 'medium_phone', '-port', '5554', '-no-snapshot'],
              env={**os.environ, 'ANDROID_HOME': str(SDK), 'ANDROID_SDK_ROOT': str(SDK)})
    run([ADB, '-s', DEVICE, 'wait-for-device'], timeout=120)
    for _ in range(120):
        if output([ADB, '-s', DEVICE, 'shell', 'getprop', 'sys.boot_completed']) == '1':
            break
        time.sleep(1)
    else:
        raise RuntimeError('Emulator did not finish booting')
    for port in (8082, 9090):
        run([ADB, '-s', DEVICE, 'reverse', f'tcp:{port}', f'tcp:{port}'])
    health = subprocess.run([str(ADB), '-s', DEVICE, 'shell', 'toybox', 'nc', '-w', '3', '10.0.2.2', '8082'],
                            input=b'GET /app/health HTTP/1.0\r\nHost: localhost\r\n\r\n', capture_output=True, timeout=10)
    if b'200 OK' not in health.stdout:
        raise RuntimeError('Emulator cannot reach the API at 10.0.2.2:8082')
    run([ADB, '-s', DEVICE, 'shell', 'input', 'keyevent', 'KEYCODE_WAKEUP'])


def start(app=True):
    verify_pins()
    if read_json(STATE / 'prepared.json').get('stack') != STACK:
        raise RuntimeError('Run prepare first; the binaries must match stack.json')
    runtime = read_json(STATE / 'runtime.json', {'processes': {}, 'containers': []})
    ports = {'auth': 8081, 'platform': 8080, 'gateway': 8082, 'mail': 8090, 'portal': 3000}
    check_ports([port for name, port in ports.items() if not (name in runtime['processes'] and alive(runtime['processes'][name]))])
    start_containers()
    if not any(name in runtime['processes'] and alive(runtime['processes'][name]) for name in ('auth', 'platform')):
        database_setup()
    spawn('mail', [sys.executable, ROOT / 'local_http.py', '8090'])
    for name in ('auth', 'platform'):
        spawn(name, [ROOT / 'bin' / name], SERVICES / name, service_env(name))
    spawn('gateway', [sys.executable, ROOT / 'local_http.py', '8082'])
    for path in ('auth/health', 'app/health'):
        wait_url('http://127.0.0.1:8082/' + path)
    start_portal()
    emulator()
    if app:
        start_app()
    print('Portal: http://localhost:3000 | Inbox: http://localhost:8090', flush=True)
    print('Flutter build/run log: booking-local/logs/flutter.log', flush=True)



def start_app():
    runtime = read_json(STATE / 'runtime.json', {'processes': {}})
    if 'flutter' in runtime['processes'] and alive(runtime['processes']['flutter']):
        return
    flutter_env = {**os.environ, 'ANDROID_HOME': str(SDK), 'ANDROID_SDK_ROOT': str(SDK)}
    app_dir = APP / 'app_demo_highfield'
    # Install only the emulator ABI. Unlike flutter run, a failed install must
    # never silently uninstall the old app and erase its private review data.
    with (LOGS / 'build-app-split.log').open('w') as log:
        run([FLUTTER, 'build', 'apk', '--debug', '--no-pub', '--target-platform',
             'android-x64', '--split-per-abi'], cwd=app_dir, env=flutter_env,
            stdout=log, stderr=subprocess.STDOUT)
    check_disk()
    apk = app_dir / 'build/app/outputs/flutter-apk/app-x86_64-debug.apk'
    run([ADB, '-s', DEVICE, 'install', '-r', '-t', apk], timeout=180)
    run([ADB, '-s', DEVICE, 'shell', 'am', 'start', '-n',
         'com.chaanz.app_demo_highfield/com.chaanz.app.MainActivity'])
    spawn('flutter', [FLUTTER, 'attach', '-d', DEVICE, '--app-id',
                     'com.chaanz.app_demo_highfield', '--pid-file', STATE / 'flutter.pid'],
          app_dir, flutter_env)


def start_portal():
    configure_portal_images()
    auth = dotenv(SERVICES / 'auth/.config/.env.development')
    env = {**os.environ, 'NEXT_PUBLIC_BASE_URL': 'http://localhost:8082',
           'NEXT_PUBLIC_BASE_ADMIN_URL': 'http://localhost:8082/admin',
           'AUTH_ADMIN_BASICAUTH_USERNAME': auth['ADMIN_BASIC_AUTH_USERNAME'],
           'AUTH_ADMIN_BASICAUTH_PASSWORD': auth['ADMIN_BASIC_AUTH_PASSWORD'],
           'NEXT_TELEMETRY_DISABLED': '1', 'CHAANZ_LOCAL_BOOKING': '1'}
    spawn('portal', ['node', 'node_modules/next/dist/bin/next', 'dev', '--webpack', '--hostname', '127.0.0.1', '--port', '3000'], PORTAL, env)


def stop_one(name):
    state = read_json(STATE / 'runtime.json', {'processes': {}, 'containers': []})
    item = state['processes'].get(name)
    if item and alive(item):
        os.killpg(item['pid'], signal.SIGTERM)
        for _ in range(50):
            if not alive(item):
                break
            time.sleep(0.1)
        else:
            if alive(item):
                os.killpg(item['pid'], signal.SIGKILL)
    state['processes'].pop(name, None)
    save(STATE / 'runtime.json', state)


def stop():
    state = read_json(STATE / 'runtime.json', {'processes': {}, 'containers': []})
    for name in reversed(list(state['processes'])):
        stop_one(name)
    for name in reversed(state['containers']):
        run(['docker', 'stop', name])
    save(STATE / 'runtime.json', {'processes': {}, 'containers': []})


def restore_overrides():
    runtime = read_json(STATE / 'runtime.json', {'processes': {}})
    if any(alive(item) for item in runtime['processes'].values()):
        raise RuntimeError('Stop this stack before restoring local overrides')
    records = read_json(STATE / 'overrides.json')
    for relative, record in records.items():
        path = WORKSPACE / relative
        if hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
            raise RuntimeError(f'{relative} has additional edits; reconcile them before restoring')
    for relative, record in records.items():
        shutil.copyfile(ROOT / record['original'], WORKSPACE / relative)
    save(STATE / 'overrides.json', {})
    (STATE / 'prepared.json').unlink(missing_ok=True)
    print('Restored tracked source overrides. Generated build files and caches are retained.')


def main():
    os.umask(0o077)
    for name in ('state', 'logs', 'bin', 'tmp'):
        (ROOT / name).mkdir(exist_ok=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'start', 'status', 'stop', 'reload', 'restart-app', 'stop-app', 'restart-auth', 'restart-platform', 'restart-portal', 'restore-overrides'])
    parser.add_argument('--no-app', action='store_true', help='Start backend, portal and emulator; launch app from VS Code yourself')
    args = parser.parse_args()
    with (STATE / 'operation.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action not in ('stop', 'stop-app', 'restore-overrides'):
            print(check_disk(), flush=True)
        if args.action == 'prepare':
            prepare()
        elif args.action == 'start':
            start(not args.no_app)
        elif args.action == 'stop':
            stop()
        elif args.action == 'stop-app':
            stop_one('flutter')
        elif args.action == 'restore-overrides':
            restore_overrides()
        elif args.action == 'restart-portal':
            stop_one('portal')
            start_portal()
        elif args.action in ('reload', 'restart-app'):
            pid = int((STATE / 'flutter.pid').read_text())
            # Flutter's PID may be a descendant of the shell entry point; verify command line.
            if b'flutter_tools' not in Path(f'/proc/{pid}/cmdline').read_bytes():
                raise RuntimeError('Flutter PID is stale')
            os.kill(pid, signal.SIGUSR1 if args.action == 'reload' else signal.SIGUSR2)
        elif args.action in ('restart-auth', 'restart-platform'):
            name = args.action.removeprefix('restart-')
            build(name)
            stop_one(name)
            spawn(name, [ROOT / 'bin' / name], SERVICES / name, service_env(name))
        else:
            runtime = read_json(STATE / 'runtime.json', {'processes': {}, 'containers': []})
            for name, item in runtime['processes'].items():
                print(f"{name}: {'running' if alive(item) else 'stopped'} (PID {item['pid']})")
            print('Containers started by this session: ' + ', '.join(runtime['containers']))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        print(f'Booking local: {error}', file=sys.stderr)
        print(f'See {LOGS}; use stop to stop only resources owned by this session.', file=sys.stderr)
        sys.exit(1)

