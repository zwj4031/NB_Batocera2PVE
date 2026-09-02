import tkinter as tk
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from pve_common import (
    run_sync_cmd, _TEST_PANEL_SRC, center_window, extract_deb_data_tar,
    _valid_deb, _fetch_url,
)
from pve_deploy_core import _DeployCoreMixin
from pve_deploy_bundle import _DeployBundleMixin
from pve_deploy_install import _DeployInstallMixin

class SunshineInstallerDialog(_DeployCoreMixin, _DeployBundleMixin, _DeployInstallMixin, tk.Toplevel):
    """向后兼容门面: 实现分散在 mixin 中, 行为与旧 pve_stream.py 完全一致。"""
    pass
