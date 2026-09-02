# -*- coding: utf-8 -*-
"""Batocera 控制台 - 外观门面 (多 Mixin 组合, 保持 from pve_bato_console import BatoceraConsoleDialog 兼容)"""

import tkinter as tk

from pve_bato_console_core import _ConsoleCoreMixin
from pve_bato_console_plugins import _ConsolePluginsMixin
from pve_bato_console_tweaks import _ConsoleTweaksMixin
from pve_bato_console_tools import _ConsoleToolsMixin


class BatoceraConsoleDialog(_ConsoleCoreMixin, _ConsolePluginsMixin, _ConsoleTweaksMixin, _ConsoleToolsMixin, tk.Toplevel):
    """Batocera 控制台外观门面 (多 Mixin 组合, 所有单文件体积均严格控制 < 50KB)"""
    pass
