"""Cross-platform command line for the campus network auto authenticator.

Everything OS-specific lives behind ``platforms.<os>``; this file only routes
commands. It works with Python 3.8 on Windows 7 and later, macOS and Linux, and
never needs a browser to sign in. Never log browser exceptions or credentials.
"""
from __future__ import annotations
import getpass
import os
import platform
import sys
import time
from pathlib import Path

import campus_core as core
import platforms
import portal_http
from setup_ui import run_setup

SCRIPT = Path(__file__).resolve()
RUN_ARGV = [str(SCRIPT), 'run']
# How long `start` waits for the child to take the lock before calling it a
# failure. A broken install should surface here, not fifteen minutes later.
START_TIMEOUT = 6
USAGE = """用法: campus_auth.py <命令>

  setup             录入或更新凭据，并启动后台监控
  start             后台启动监控
  status            查看监控状态
  stop              停止监控（等待当前操作结束，最多 90 秒）
  check             立即检测互联网连通性
  auth [账号]       立即尝试一次认证（已联网时不做任何事）
  login-http [账号] 只走 HTTP 认证，用于排查门户协议
  logs              打印日志目录
  run               前台运行监控（供系统服务调用）
  install-startup   设置当前用户登录后自启动
  remove-startup    取消自启动
  uninstall         停止监控、取消自启动并删除本工具保存的凭据
"""


def build_authenticator(backends, config):
    return core.Authenticator(
        backends.credentials,
        mode=config['auth_mode'],
        portal=config['portal'],
        browser_factory=backends.browser,
    )


def monitor(backends, config):
    core.configure_logging()
    if not backends.lock.acquire():
        core.log.info('ALREADY_RUNNING')
        return 0
    stop = backends.stop
    login = build_authenticator(backends, config)
    try:
        stop.install_handlers()
        core.log.info('MONITOR_STARTED platform=%s auth_mode=%s interval=%ss pid=%d python=%s',
                      backends.name, config['auth_mode'], config['interval'],
                      os.getpid(), platform.python_version())
        # An unattended daemon that exits on one bad cycle is worse than one that
        # logs and retries: nobody is watching to restart it.
        while not stop.stopped():
            try:
                core.monitor_loop(
                    stop.stopped,
                    stop.wait,
                    backends.wifi.ensure,
                    login,
                    stop.request,
                    interval=config['interval'],
                    heartbeat=lambda state: core.record_state(**state),
                )
            except Exception:
                core.log.warning('MONITOR_RESTART: loop failed, retrying in 30s')
                stop.wait(30)
    finally:
        stop.request()
        stop.close()
        # Log before releasing the lock: `stop` treats a free lock as "the
        # monitor is gone", so the final line is on disk by the time it returns.
        core.log.info('MONITOR_STOPPED')
        backends.lock.release()
    return 0


def start(backends):
    """Launch the monitor and wait until it holds the lock.

    Returns 'already', 'started' or 'failed'. Reporting success before the child
    is actually up hides a broken install until the next outage.
    """
    if platforms.running():
        return 'already'
    backends.spawn(RUN_ARGV)
    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline:
        if platforms.running():
            return 'started'
        time.sleep(0.2)
    return 'failed'


def describe_state(state):
    if not state.get('checked'):
        return ', no heartbeat yet'
    age = max(0, int(time.time() - state['checked']))
    return ', last check %ds ago, %s, %d failures' % (
        age, 'online' if state.get('online') else 'offline', state.get('failures', 0))


def http_only(backends, config, account):
    """Diagnostic path: one HTTP login, no browser, explicit account allowed."""
    stored = None
    try:
        stored = backends.credentials.read()
    except Exception:
        stored = None
    if not account:
        if not stored:
            print('CREDENTIALS_MISSING: 请先运行 setup。', file=sys.stderr)
            return 1
        account = stored[0]
    secret = None
    if stored and stored[0].split('@')[0] == account.split('@')[0]:
        secret = stored[1]
        print('使用本机已保存的凭据。')
    if not secret:
        if not sys.stdin or not sys.stdin.isatty():
            print('需要在交互式终端中运行，或先完成 setup。', file=sys.stderr)
            return 1
        secret = getpass.getpass('密码: ')
    result = portal_http.login(account, secret, portal=config['portal'])
    secret = None
    if result.success:
        print('HTTP 登录成功。')
        return 0
    print('HTTP 登录失败：' + result.reason)
    return 1


def authenticate(backends, config, account=None):
    core.configure_logging()
    if account:
        # Diagnostic path: attempt regardless of the current state, so the
        # portal protocol can be checked even while a session is online.
        return http_only(backends, config, account)
    if core.internet_ok():
        print('Already online; nothing to do.')
        return 0
    ok = build_authenticator(backends, config)(lambda: False)
    print('Authenticated.' if ok else 'Authentication failed; see the log.')
    return 0 if ok else 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # Disable Playwright verbose output even when inherited from a dev shell.
    os.environ.pop('DEBUG', None)
    os.environ.pop('PWDEBUG', None)
    command = argv[0] if argv else 'status'
    if command in ('help', '-h', '--help'):
        print(USAGE)
        return 0
    if command == 'check':
        print('Online' if core.internet_ok() else 'All probes failed')
        return 0
    if command == 'logs':
        print(core.configure_logging())
        return 0
    config = core.load_config()
    try:
        backends = platforms.load(SCRIPT)
    except ImportError as exc:
        print('缺少平台依赖: %s' % exc, file=sys.stderr)
        print('请先按 README 安装本平台的依赖。', file=sys.stderr)
        return 2
    except RuntimeError:
        print('当前系统暂不支持: %s' % sys.platform, file=sys.stderr)
        return 2

    if command == 'setup':
        run_setup(backends.credentials, lambda: start(backends) != 'failed')
        return 0
    if command == 'run':
        return monitor(backends, config)
    if command == 'start':
        outcome = start(backends)
        if outcome == 'already':
            print('Already running.')
            return 0
        if outcome == 'started':
            print('Started.')
            return 0
        print('Start failed: the monitor did not take the lock; see the log.',
              file=sys.stderr)
        return 1
    if command == 'stop':
        if platforms.stop_running():
            print('Stopped.')
            return 0
        print('Stop timed out; the monitor is still running.', file=sys.stderr)
        return 1
    if command == 'status':
        # Exit code follows systemctl: 0 running, 1 stopped, so a cron job or a
        # health check can rely on it without parsing text.
        if not platforms.running():
            print('Stopped')
            return 1
        print('Running (%s, auth_mode=%s)%s'
              % (backends.name, config['auth_mode'], describe_state(core.read_state())))
        return 0
    if command in ('auth', 'login-http'):
        # 带账号时只走 HTTP，用于排查门户协议；不带时按 auth_mode 走完整链路。
        account = argv[1] if len(argv) > 1 else None
        return authenticate(backends, config, account)
    if command == 'install-startup':
        try:
            backends.autostart.install(RUN_ARGV)
        except (OSError, ValueError) as exc:
            # The message is a fixed identifier such as `systemd_enable_failed`;
            # the platform code never puts a path or a credential in it.
            print('Startup install failed: %s' % exc, file=sys.stderr)
            return 1
        print('Startup installed for the current user.')
        return 0
    if command == 'remove-startup':
        try:
            backends.autostart.remove()
        except (OSError, ValueError) as exc:
            print('Startup removal failed: %s' % exc, file=sys.stderr)
            return 1
        print('Startup removed.')
        return 0
    if command == 'uninstall':
        if not platforms.stop_running():
            # Removing credentials under a live monitor would leave it failing
            # with CREDENTIALS_MISSING and no way to tell why.
            print('Stop timed out; nothing was removed.', file=sys.stderr)
            return 1
        backends.autostart.remove()
        backends.credentials.delete()
        print('Stopped; startup entry and this tool credential removed. Project files retained.')
        return 0
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception:
        # Suppress sensitive exception values in every mode.
        if sys.stderr:
            print('Operation failed; no sensitive details recorded.', file=sys.stderr)
        sys.exit(1)
