# -*- coding: utf-8 -*-

from . import const
from . import controllers
from . import models

# 17.0+ 正確的導入路徑通常需要進到 sub-module
from odoo.addons.payment import utils as payment_utils

def post_init_hook(env):
    """ 
    模仿 Stripe 的邏輯，但使用正確的 API 調用。
    注意：如果 payment_utils 裡找不到 setup_provider，
    說明該版本已完全自動化，你可以直接 pass。
    """
    try:
        payment_utils.setup_provider(env, 'airwallex')
    except AttributeError:
        # 如果版本更新導致方法徹底消失，記錄一下即可，系統會透過 XML 自動處理
        import logging
        logging.getLogger(__name__).info("payment.utils.setup_provider 不存在，跳過手動初始化。")

def uninstall_hook(env):
    try:
        payment_utils.reset_payment_provider(env, 'airwallex')
    except AttributeError:
        pass