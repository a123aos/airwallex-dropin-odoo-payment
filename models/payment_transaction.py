# -*- coding: utf-8 -*-
import logging
from odoo import _, api, fields, models
from odoo.addons.payment_airwallex import const

_logger = logging.getLogger(__name__)

class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    airwallex_client_secret = fields.Char(string="Airwallex Client Secret", groups='base.group_system')

    # === 商業邏輯 - 預處理 ===

    def _get_specific_processing_values(self, processing_values):
        res = super()._get_specific_processing_values(processing_values)
        if self.provider_code != 'airwallex' or self.operation == 'online_token':
            return res

        # 確保前台 Public User 結帳時有權限將 Airwallex 金鑰寫入交易記錄，提權使用 .sudo()
        if not self.provider_reference or not self.airwallex_client_secret:
            intent_data = self.provider_id._airwallex_create_intent(self)
            self.sudo().write({
                'provider_reference': intent_data.get('intent_id'),
                'airwallex_client_secret': intent_data.get('client_secret'),
            })

        res.update({
            'client_secret': self.airwallex_client_secret,
            'intent_id': self.provider_reference,
            'currency': self.currency_id.name,
            'amount': self.amount,
            'airwallex_auto_capture': not self.provider_id.capture_manually,
        })

        # =========================================================================
        # === 【核心修正】刪除 api_url，徹底根治 400 CSRF 錯誤 ====================
        # =========================================================================
        # 移除父類別自動帶入的 api_url，Odoo 前端就不會再執行傳統的 HTTP POST 表單提交。
        # 這能 100% 避免無 Token 請求引發的 CSRF 報錯，並將主導權完全保留給您的前端 JS。
        if 'api_url' in res:
            del res['api_url']

        return res

    # === 商業邏輯 - 核心狀態同步 ===

    def _process_notification_data(self, notification_data):
        if self.provider_code != 'airwallex':
            return super()._process_notification_data(notification_data)

        # 防併發：在處理前先鎖定該筆記錄
        self.ensure_one()
        self.env.cr.execute("SELECT id FROM payment_transaction WHERE id = %s FOR UPDATE", (self.id,))
        
        _logger.info("Airwallex: 處理通知資料: %s", notification_data)
        self._apply_updates(notification_data)

    def _apply_updates(self, notification_data):
        if self.provider_code != 'airwallex':
            return super()._apply_updates(notification_data)

        air_obj = notification_data.get('airwallex_obj', {})
        status = air_obj.get('status', '').upper()
        
        # 處理初始狀態：如果是初始意圖建立或瀏覽狀態，直接跳過，保持 Draft
        if status in ['REQUIRES_PAYMENT_METHOD', 'REQUIRES_CUSTOMER_ACTION'] and self.state == 'draft':
            _logger.info("Airwallex: 偵測到 Intent 預備狀態 %s，維持 Draft，不變更訂單。", status)
            return

        mapping = const.REFUND_STATUS_MAPPING if self.operation == 'refund' else const.PAYMENT_STATUS_MAPPING
        new_state = mapping.get(status)

        # 狀態防禦：狀態相同時跳過
        if self.state == new_state:
            return

        # 購物車保護：支付過程中收到不確定狀態時，不標記為取消
        if new_state in ['cancel', 'error'] and self.state in ['draft', 'pending']:
            return

        # 正常狀態流轉
        if new_state == 'done':
            self._set_done()
        elif new_state == 'pending':
            self._set_pending()
        elif new_state == 'authorized':
            self._set_authorized()
        elif new_state == 'cancel':
            self._set_canceled()
        elif new_state == 'error':
            self._set_error(_("Airwallex 交易處理錯誤: %s") % status)

        # 觸發後續核銷
        if self.operation == 'refund' and self.state == 'done':
            self.env.ref('payment.cron_post_process_payment_tx')._trigger()

    # === 商業邏輯 - 輔助工具 ===

    @api.model
    def _search_by_reference(self, provider_code, payment_data):
        if provider_code != 'airwallex':
            return super()._search_by_reference(provider_code, payment_data)

        air_obj = payment_data.get('airwallex_obj', {})
        provider_ref = air_obj.get('id')
        if provider_ref:
            tx = self.search([('provider_reference', '=', provider_ref), ('provider_code', '=', 'airwallex')], limit=1)
            if tx: return tx

        reference = payment_data.get('reference') or air_obj.get('merchant_order_id')
        return self.search([('reference', '=', reference), ('provider_code', '=', 'airwallex')], limit=1) if reference else self.env['payment.transaction']

    def _extract_amount_data(self, payment_data):
        if self.provider_code != 'airwallex':
            return super()._extract_amount_data(payment_data)

        air_obj = payment_data.get('airwallex_obj', {})
        
        # 安全解析：防止 KeyError，若 API 無金額資料則回退使用交易單本身金額
        raw_amount = air_obj.get('amount')
        amount = abs(float(raw_amount)) if raw_amount is not None else self.amount
        currency_code = air_obj.get('currency') or self.currency_id.name

        return {
            'amount': amount,
            'currency_code': currency_code.upper(),
        }
