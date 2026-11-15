"""Credential setup: a small window when a desktop is available, a prompt when not.

Shared by every platform so the wording and the validation stay identical. The
password is handed straight to the credential store; it is never echoed, never
passed as an argument and never written to the log.
"""
from __future__ import annotations
import getpass
import sys

TITLE = '校园网 eLearning 凭据设置'


def storage_note():
    if sys.platform == 'win32':
        return '凭据仅存入本机 Windows 凭据管理器。'
    if sys.platform == 'darwin':
        return '凭据仅存入本机 macOS 钥匙串。'
    return '凭据仅存入本机系统密钥环；密钥环不可用时退回 0600 权限的本地文件。'


def normalize(user):
    user = user.strip()
    if user.endswith('@study'):
        user = user[:-6]
    return user


def _save(store, user, secret):
    user = normalize(user)
    if not user or not secret:
        return '请输入账号和密码。'
    try:
        store.write(user, secret)
    except Exception:
        return '无法写入本机凭据存储。'
    return None


def _dialog(store, on_saved):
    import tkinter as tk
    from tkinter import messagebox

    window = tk.Tk()
    window.title(TITLE)
    window.resizable(False, False)
    tk.Label(window, text=storage_note() + '\n账号无需添加 @study；密码不会写入日志。',
             padx=25, pady=15).grid(row=0, columnspan=2)
    tk.Label(window, text='账号').grid(row=1, column=0)
    username = tk.Entry(window, width=32)
    username.grid(row=1, column=1, padx=15, pady=8)
    tk.Label(window, text='密码').grid(row=2, column=0)
    password = tk.Entry(window, show='●', width=32)
    password.grid(row=2, column=1, padx=15, pady=8)

    def save():
        problem = _save(store, username.get(), password.get())
        if problem:
            messagebox.showerror('未保存', problem)
            return
        password.delete(0, tk.END)
        username.delete(0, tk.END)
        try:
            started = on_saved() is not False
        except Exception:
            started = False
        messagebox.showinfo('已保存', '凭据已保存，后台监控已启动。' if started
                            else '凭据已保存，但后台监控启动失败，请运行 start。')
        window.destroy()

    tk.Button(window, text='保存凭据并启动', command=save).grid(row=3, columnspan=2, pady=18)
    username.focus_set()
    window.mainloop()
    return True


def _console(store, on_saved):
    if not sys.stdin or not sys.stdin.isatty():
        print('需要在交互式终端中运行；无人值守请先在有终端的环境完成 setup。', file=sys.stderr)
        return False
    print(storage_note())
    print('账号无需添加 @study；密码输入时不会回显，也不会写入日志。')
    try:
        user = input('账号: ')
        secret = getpass.getpass('密码: ')
    except (EOFError, KeyboardInterrupt):
        print('\n已取消。')
        return False
    problem = _save(store, user, secret)
    secret = None
    if problem:
        print(problem)
        return False
    try:
        started = on_saved() is not False
    except Exception:
        started = False
    print('凭据已保存，后台监控已启动。' if started
          else '凭据已保存，但后台监控启动失败，请运行 start。')
    return True


def run_setup(store, on_saved):
    try:
        return _dialog(store, on_saved)
    except Exception:
        # No display, no Tk, or no window system: the console path is enough.
        return _console(store, on_saved)
